import itertools
import multiprocessing
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Annotated, Optional, List

import typer
from rich import print, progress

from simulation import AvailableData, simulate, base_simulation, end_simulation

if 'SUMO_HOME' in os.environ:
    sys.path.append(os.path.join(os.environ['SUMO_HOME'], 'tools'))

import sumolib

import matplotlib.pyplot as plt

app = typer.Typer()


def reference_simulation(gui, config, closed_street, debug):
    return base_simulation(config.absolute(), 0, closed_street, gui=gui, debug=debug)


def closed_street_simulation(gui, config, delay, closed_street, affected, wrong, _progress, task_id, preferred_street,
                             debug):
    return simulate(gui, config, delay, closed_street, preferred_street, affected, wrong, task_id,
                    _progress=_progress, keep_running=True, debug=debug,
                    log_duration=False, log_emissions=False, log_statistics=False, log_edgedata=False)


def get_options(net, closed_id, options, closed_edges):
    incoming = net.getEdge(closed_id).getIncoming()  # all edges that are in a 'connection' to the closed one
    # the closed edge may be an edge connected to the 'real' closed one that had it as the only connection

    # I need to also exclude all edges that are connected to a closed edge
    incoming = [i for i in incoming if i.getID() not in closed_edges]

    for connection in incoming:
        # take all connected edges except the current one
        alternatives = [c for c in connection.getOutgoing() if c.getID() not in closed_edges]

        if len(alternatives) > 0:
            # for this edge there are options that are not the closed edge

            current = options.setdefault(connection.getID(), [])
            for edge in alternatives:
                if edge.getID() not in current:
                    options[connection.getID()].append(edge.getID())
        else:
            # the edge is only connected to the closed one. I need to go back an edge
            connection_id = connection.getID()
            if connection_id not in closed_edges:
                closed_edges.append(connection_id)  # I can treat this edge as closed
                get_options(net, connection_id, options, closed_edges)


def analyze_network(net_file, closed_edges):
    options = {}  # {'edge_id': ['opzione1', 'opzione2'],}

    net = sumolib.net.readNet(net_file)
    for edge in closed_edges:
        get_options(net, edge, options, closed_edges)

    return options


def generate_environments(options):
    keys = list(options.keys())
    lists = list(options.values())

    # Generate all combinations
    combinations = itertools.product(*lists)

    # Convert combinations into a list of dictionaries
    choices = [[{'origin': key, 'destination': value} for key, value in zip(keys, combination)]
               for combination in combinations]

    return choices


@app.command()
def main(config: Path,
         close: Annotated[Optional[List[str]], typer.Option()] = None,
         graph: Annotated[Optional[List[AvailableData]], typer.Option()] = None,
         show_gui: bool = False, debug: bool = False):
    if config.is_dir():
        print("Config is a directory, should be a file")
        raise typer.Abort()
    elif not config.exists():
        print("The given config doesn't exist")
        raise typer.Abort()
    else:
        config = config.absolute()

    if not graph:
        parameters = [e for e in list(AvailableData.__members__)]
    else:
        parameters = graph

    concurrent = 1 if show_gui else os.cpu_count()
    delay = "3" if show_gui else "0"

    closed_street = close if close else []

    # FETCH NEIGHOURING EDGES

    net_file_name = list(sumolib.xml.parse(config, 'net-file'))[0].value
    net_file = os.path.join(os.path.split(config)[0], net_file_name)

    options = analyze_network(net_file, closed_street)
    environments = generate_environments(options)

    pre_result = reference_simulation(show_gui, config.absolute(), closed_street, debug)
    baseline = {p: float(pre_result[p] if len(str(pre_result[p])) > 0 else 0) for p in parameters}
    affected = pre_result["affected"]
    wrong = pre_result["wrong"]
    total = pre_result["total"]

    print("[blue]Completed reference simulation")

    # RUN PARALLEL SIMULATIONS

    jobs = []

    num = len(environments)
    if num > 0:
        with progress.Progress(
                "[progress.description]{task.description}",
                progress.BarColumn(),
                progress.MofNCompleteColumn(),
                progress.TextColumn("•"),
                "[progress.percentage]{task.percentage:>3.0f}%",
                progress.TimeElapsedColumn(),
        ) as all_progress:
            with multiprocessing.Manager() as manager:
                _progress = manager.dict()
                overall_progress_task = all_progress.add_task("[green]Simulations progress:")

                with ProcessPoolExecutor(max_workers=concurrent) as executor:
                    for n in range(num):
                        task_id = all_progress.add_task(f"task {n}", visible=False, total=None)
                        jobs.append(
                            executor.submit(closed_street_simulation, show_gui, config, delay, closed_street,
                                            affected, wrong, _progress, task_id, environments[n], debug))

                    while (n_finished := sum([future.done() for future in jobs])) < len(jobs):
                        all_progress.update(overall_progress_task, completed=n_finished, total=len(jobs))
                        for task_id, update_data in _progress.items():
                            # desc = update_data["description"]
                            latest = update_data["progress"]
                            all_progress.update(
                                task_id, completed=latest, total=total, visible=latest < total)

                    for i in range(concurrent):
                        executor.submit(end_simulation)

            all_progress.update(
                overall_progress_task, description="All simulations completed", completed=len(jobs), total=len(jobs))

    # PLOT RESULTS

    for parameter in parameters:
        x = []
        y = []
        x_vals = ["reference"]
        y_vals = [baseline[parameter]]
        if len(jobs) > 0:
            for future in jobs:
                result = future.result()
                x.append(f'{result["id"]}')  # ({result["pref_street_name"]})
                y.append(float(result[parameter]) if len(str(result[parameter])) > 0 else 0)

            sorted_y, sorted_x = zip(*sorted(zip(y, x)))
            x_vals.extend(list(sorted_x))
            y_vals.extend(list(sorted_y))

        fig = plt.figure(figsize=(12, 6))
        fig.canvas.manager.set_window_title(parameter)
        plt.xticks(rotation=45, ha="right")
        plt.scatter(x_vals, y_vals)
        plt.axhline(y=baseline[parameter], color='black', linestyle='--')

        plt.title(parameter)
        plt.tight_layout()
    plt.show()

    for i in range(len(environments)):
        destinations = [e['destination'] for e in environments[i]]
        # TODO: add origins -> destinations in str
        print(f'{i}: [green]{" ".join(str(d) for d in destinations)}')

    exited = False
    while not exited:
        s = str(input(f"Choose a simulation to view (0-{len(environments) - 1} / q to exit): "))
        if s.isdigit() and 0 <= int(s) < len(environments):
            simulate(True, config, 10, closed_street, environments[int(s)], affected, wrong, s, auto=False)
        elif s in ["q", "Q"]:
            exited = True


if __name__ == '__main__':
    app()

# TODO: maybe rewrite from the pov of destinations instead of origins
# TODO: add weighted mode
# TODO: improve retrieved data + generate heatmaps

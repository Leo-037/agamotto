import multiprocessing
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Annotated, Optional, List
import matplotlib.pyplot as plt

import typer
from rich import print as rprint, progress

from analysis import get_net_from_cfg, analyze_network, generate_combinations, pretty_combination
from simulation import AvailableData, simulate, base_simulation, end_simulation, NAVIGATION, SIGN

if 'SUMO_HOME' in os.environ:
    sys.path.append(os.path.join(os.environ['SUMO_HOME'], 'tools'))

app = typer.Typer()


@app.command()
def main(config: Path,
         close: Annotated[Optional[List[str]], typer.Option()] = None,
         graph: Annotated[Optional[List[AvailableData]], typer.Option()] = None,
         show_gui: bool = False, debug: bool = False):
    if config.is_dir():
        rprint("Config is a directory, should be a file")
        raise typer.Abort()
    elif not config.exists():
        rprint("The given config doesn't exist")
        raise typer.Abort()
    else:
        config = config.absolute()

    if not graph:
        parameters = [e for e in list(AvailableData.__members__)]
    else:
        parameters = graph

    concurrent = 1 if show_gui else os.cpu_count()
    delay = "3" if show_gui else "0"

    closed_edges = close if close else []

    # FETCH NEIGHOURING EDGES

    net_file = get_net_from_cfg(config)
    options = analyze_network(net_file, closed_edges)

    environments = []
    for combination in generate_combinations(options):
        environments.append({'strategy': NAVIGATION, 'combination': combination})
        environments.append({'strategy': SIGN, 'combination': combination})

    # RUN REFERENCE SIMULATION

    pre_result = base_simulation(config, 0, closed_edges, gui=show_gui, debug=debug)
    baseline = {p: float(pre_result[p] if len(str(pre_result[p])) > 0 else 0) for p in parameters}
    affected = pre_result["affected"]
    wrong = pre_result["wrong"]
    total = pre_result["total"]

    rprint("[blue]Completed reference simulation")

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
                            executor.submit(simulate, show_gui, config, delay, closed_edges, environments[n], affected,
                                            wrong, task_id, _progress=_progress, debug=debug, keep_running=True,
                                            auto=True, log_duration=False, log_emissions=False,
                                            log_statistics=False,
                                            log_edgedata=False))

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

            sorted_x, sorted_y = zip(*sorted(zip(x, y), key=mysort))
            x_vals.extend(list(sorted_x))
            y_vals.extend(list(sorted_y))

        fig = plt.figure(figsize=(12, 6))
        fig.canvas.manager.set_window_title(parameter)
        # plt.xticks(rotation=45, ha="right")

        plt.scatter(x_vals[0], y_vals[0], color="black")

        # Plot pairs of points with different colors
        for i in range(1, len(x_vals) - 1, 2):
            plt.scatter(x_vals[i:i + 2], y_vals[i:i + 2], color=f"C{i // 2 + 1}")
            plt.axvspan(float(x_vals[i]) - 0.5, float(x_vals[i + 1]) + 0.5, color=f"C{i // 2 + 1}", alpha=0.1)

        plt.axhline(y=baseline[parameter], color='black', linestyle='--')

        plt.title(parameter)
        plt.tight_layout()
    plt.show()

    print("")
    for i in range(len(environments)):
        env = environments[i]
        rprint(f'{i + 1}/{env['strategy']}: {pretty_combination(env['combination'])}')

    exited = False
    while not exited:
        s = str(input(f"Choose a simulation to view (1-{len(environments)} / q to exit): "))
        if s.isdigit() and 0 <= int(s) < len(environments):
            simulate(True, config, 10, closed_edges, environments[int(s)], affected, wrong, s, auto=False)
        elif s in ["q", "Q"]:
            exited = True


def mysort(z):
    return int(z[0])


if __name__ == '__main__':
    app()

# TODO: add weighted mode
# TODO: improve retrieved data + generate heatmaps

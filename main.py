import multiprocessing
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Annotated, Optional, List
import matplotlib.pyplot as plt

import typer
from rich import print as rprint
from rich.console import Group
from rich.live import Live
from rich.panel import Panel
from rich.progress import Progress, BarColumn, MofNCompleteColumn, TextColumn, TimeElapsedColumn

from analysis import get_net_from_cfg, analyze_network, generate_combinations, pretty_combination
from simulation import AvailableData, base_simulation, show_simulation, NAVIGATION, SIGN, batch_simulation

if 'SUMO_HOME' in os.environ:
    sys.path.append(os.path.join(os.environ['SUMO_HOME'], 'tools'))

app = typer.Typer()

# PROGRESS BARS

overall_progress = Progress(
    "[progress.description]{task.description}",
    BarColumn(),
    MofNCompleteColumn(),
    TextColumn("•"),
    "[progress.percentage]{task.percentage:>3.0f}%",
    TimeElapsedColumn(),
)
thread_progress = Progress(
    "[progress.description]{task.description}",
    BarColumn(),
    MofNCompleteColumn(),
    TextColumn("•"),
    "[progress.percentage]{task.percentage:>3.0f}%",
    TimeElapsedColumn(),
    TextColumn("[bold blue]{task.fields[completed_sims]}/{task.fields[total_sims]}", justify="right"),
)
progress_group = Group(
    Panel(thread_progress), overall_progress,
)


def distribution(num, min_len, max_n_array):
    """
    Distribution of simulations environments will take into account how many threads are available
    and the minimum number of runs to schedule on a single thread before 'overflowing' on another thread.
    """

    n_array_with_min_len = min(num // min_len, max_n_array)
    remaining_elements = num - (n_array_with_min_len * min_len)
    distributed_array = [min_len] * n_array_with_min_len

    i = 0
    while remaining_elements > 0:
        if len(distributed_array) < max_n_array:
            amount = min(min_len, remaining_elements)
            distributed_array.append(amount)
            remaining_elements -= amount
        else:
            distributed_array[i] += 1
            remaining_elements -= 1
            if i + 1 == max_n_array:
                i = 0
            else:
                i += 1

    return distributed_array


@app.command()
def main(config: Path,
         close: Annotated[Optional[List[str]], typer.Option()] = None,
         graph: Annotated[Optional[List[AvailableData]], typer.Option()] = None,
         show_gui: bool = False, debug: bool = False,
         min_sim: int = 1, max_concurrent: int = os.cpu_count()):
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

    concurrent = 1 if show_gui else max_concurrent
    delay = "3" if show_gui else "0"

    closed_edges = close if close else []

    # GENERATE SIMULATION ENVIRONMENTS

    net_file = get_net_from_cfg(config)
    options = analyze_network(net_file, closed_edges)

    environments = []
    for combination in generate_combinations(options):
        environments.append({'strategy': NAVIGATION, 'combination': combination})
        environments.append({'strategy': SIGN, 'combination': combination})

    # RUN REFERENCE SIMULATION

    pre_result = base_simulation(config, 0, closed_edges, gui=show_gui, debug=False)
    baseline = {p: float(pre_result[p] if len(str(pre_result[p])) > 0 else 0) for p in parameters}
    total = pre_result["total"]

    rprint("[blue]Completed reference simulation")

    # RUN PARALLEL SIMULATIONS

    jobs = []
    num = len(environments)
    if num > 0:
        with Live(progress_group):
            overall_progress_id = overall_progress.add_task("[green]Simulations progress:")

            with multiprocessing.Manager() as manager:
                _progress = manager.dict()

                with ProcessPoolExecutor(max_workers=concurrent) as executor:
                    distributed = distribution(num, min_sim, concurrent)
                    start = 0
                    for i in range(len(distributed)):
                        end = start + distributed[i]
                        thread_id = thread_progress.add_task(f"Thread {i}", total=total,
                                                             completed_sims=0, total_sims=distributed[i])
                        jobs.append(
                            executor.submit(batch_simulation, config, delay, closed_edges, environments[start:end],
                                            thread_id, start, _progress=_progress,
                                            gui=show_gui, debug=debug))
                        start = end

                    while sum([future.done() for future in jobs]) < len(jobs):
                        total_sims = 0
                        for thread_id, update_data in _progress.items():
                            thread_latest = update_data["thread_progress"]
                            task_latest = update_data['task_progress']
                            thread_progress.update(thread_id,
                                                   completed=task_latest,
                                                   completed_sims=thread_latest)
                            total_sims += thread_latest
                        overall_progress.update(overall_progress_id,
                                                completed=total_sims, total=num)

            overall_progress.update(
                overall_progress_id, description="All simulations completed", completed=num, total=num)

    # PLOT RESULTS

    for parameter in parameters:
        x = []
        y = []
        x_vals = ["reference"]
        y_vals = [baseline[parameter]]
        if len(jobs) > 0:
            for future in jobs:
                result = future.result()
                for v in result.values():
                    x.append(f'{v["id"]}')
                    y.append(float(v[parameter]) if len(str(v[parameter])) > 0 else 0)

            sorted_x, sorted_y = zip(*sorted(zip(x, y), key=mysort))
            x_vals.extend(list(sorted_x))
            y_vals.extend(list(sorted_y))

        fig = plt.figure(figsize=(max(len(environments) / 4, 12), 6))
        fig.canvas.manager.set_window_title(parameter)

        plt.scatter(x_vals[0], y_vals[0], color="black")

        # Plot pairs of points with different colors
        for i in range(2, len(x_vals) - 1, 2):
            plt.scatter(x_vals[i:i + 2], y_vals[i:i + 2], color=f"C{i // 2 + 1}")
            plt.axvspan(float(x_vals[i]) - 0.5, float(x_vals[i + 1]) + 0.5, color=f"C{i // 2 + 1}", alpha=0.1)

        plt.axhline(y=baseline[parameter], color='black', linestyle='--')

        plt.title(parameter)
        plt.tight_layout()
    plt.show()

    print("")
    for i in range(0, len(environments), 2):
        env = environments[i]
        rprint(f'{i + 1} ([italic]NAV) | {i + 2} ([italic]SIGN) \t[default] {pretty_combination(env['combination'])}')

    exited = False
    while not exited:
        s = str(input(f"Choose a simulation to view (1-{len(environments)} / q to exit): "))
        if s.isdigit() and 0 <= int(s) < len(environments):
            show_simulation(config, 10, closed_edges, environments[int(s)])
        elif s in ["q", "Q"]:
            exited = True


def mysort(z):
    return int(z[0])


if __name__ == '__main__':
    app()

# TODO: add weighted mode
# TODO: improve retrieved data + generate heatmaps

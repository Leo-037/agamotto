import multiprocessing
import os
import shutil
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Annotated, Optional, List

import matplotlib.pyplot as plt
import typer
from click import Tuple
from rich import print as rprint
from rich.console import Group, Console
from rich.live import Live
from rich.panel import Panel
from rich.progress import Progress, BarColumn, MofNCompleteColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from analysis import get_net_from_cfg, analyze_network, generate_combinations, pretty_combination
from plotting import Plotter, SimPlotter
from simulation import AvailableData, batch_simulation, show_simulation

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
plotting_progress = Progress(
    "[progress.description]{task.description}",
    BarColumn(),
    MofNCompleteColumn(),
    TextColumn("•"),
    TimeElapsedColumn(),
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
         plot: Annotated[Optional[List[str]], typer.Option()] = None,
         weight: Annotated[Optional[List[Tuple]], typer.Option(click_type=Tuple([int, int]))] = None,
         show_gui: bool = False, debug: bool = False,
         keep_output: bool = False,
         min_sim: int = 1, max_concurrent: int = os.cpu_count()):
    if config.is_dir():
        rprint("Config is a directory, should be a file")
        raise typer.Abort()
    elif not config.exists():
        rprint("The given config doesn't exist")
        raise typer.Abort()
    else:
        config = config.absolute()

    concurrent = 1 if show_gui else max_concurrent
    delay = "3" if show_gui else "0"

    closed_edges = close if close else []

    if not weight:
        weights = [(100, 0), (0, 100), (50, 50)]
    else:
        weights = weight
    n_weights = len(weights)

    console = Console()
    console.print(f"Running with weights: {weights}")

    # GENERATE SIMULATION ENVIRONMENTS

    net_file = get_net_from_cfg(config)
    options = analyze_network(net_file, closed_edges)

    environments = [{'weights': [], 'combination': []}]  # the reference simulation
    for combination in generate_combinations(options):
        for w in weights:
            environments.append({'weights': w, 'combination': combination})

    # RUN PARALLEL SIMULATIONS

    run_folder = f'./runs/{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}'

    jobs = []
    n_envs = len(environments)
    if n_envs > 0:
        with Live(progress_group):
            overall_progress_id = overall_progress.add_task("[green]Simulations progress:", total=n_envs)

            with multiprocessing.Manager() as manager:
                _progress = manager.dict()

                with ProcessPoolExecutor(max_workers=concurrent) as executor:
                    distributed = distribution(n_envs, min_sim, concurrent)
                    start = 0
                    for i in range(len(distributed)):
                        end = start + distributed[i]
                        thread_id = thread_progress.add_task(f"Thread {i}", total=1,
                                                             completed_sims=0, total_sims=distributed[i])
                        jobs.append(
                            executor.submit(batch_simulation, config, delay, closed_edges, environments[start:end],
                                            thread_id, start, run_folder, _progress=_progress,
                                            gui=show_gui, debug=debug))
                        start = end

                    while sum([future.done() for future in jobs]) < len(jobs):
                        total_sims = 0
                        for thread_id, update_data in _progress.items():
                            thread_latest = update_data["thread_progress"]
                            task_latest = update_data['task_progress']
                            task_total = update_data['task_total']
                            total_sims += thread_latest
                            thread_progress.update(thread_id,
                                                   completed=task_latest,
                                                   total=task_total,
                                                   completed_sims=thread_latest + 1,
                                                   visible=total_sims < n_envs)
                        overall_progress.update(overall_progress_id,
                                                completed=total_sims, total=n_envs)

            overall_progress.update(
                overall_progress_id, description="All simulations completed", completed=n_envs, total=n_envs)

    # PLOT RESULTS

    for graph_type in graph:
        x = []
        y = []
        for future in jobs:
            result = future.result()
            for k, v in result.items():
                x.append(k)
                y.append(float(v[graph_type]) if len(str(v[graph_type])) > 0 else 0)

        sorted_x, sorted_y = zip(*sorted(zip(x, y), key=mysort))
        x_vals = list(sorted_x)
        y_vals = list(sorted_y)

        fig = plt.figure(figsize=(max(len(environments) / 4, 12), 6))
        fig.canvas.manager.set_window_title(graph_type)

        x_vals[0] = 'reference'
        plt.scatter(x_vals[0], y_vals[0], color="black")

        # Plot pairs of points with different colors
        for i in range(1, len(x_vals) - (n_weights - 1), n_weights):
            plt.scatter(x_vals[i:i + n_weights], y_vals[i:i + n_weights],
                        color=f"C{i // n_weights}")
            plt.axvspan(float(x_vals[i]) - 0.5, float(x_vals[i + n_weights - 1]) + 0.5,
                        color=f"C{i // n_weights}", alpha=0.1)

        plt.axhline(y=y_vals[0], color='black', linestyle='--')

        plt.title(graph_type)
        plt.tight_layout()
    plt.show(block=False)

    print()
    if plot is not None:
        with plotting_progress:
            p_id = plotting_progress.add_task("[green]Plotting simulation results:", total=n_envs)
            plotter = Plotter(run_folder, net_file)
            for r in range(n_envs):
                sim_plotter = SimPlotter(plotter, r, organize='by_metric')
                for p in plot:
                    sim_plotter.plot(p)
                plotting_progress.advance(p_id)
            plotting_progress.update(p_id, description="All simulations plotted")
            if not keep_output:
                remove_output_folder(run_folder)

    # PRINT LEGEND

    table = Table(title="Simulations", show_lines=True)

    for w in weights:
        table.add_column(f"{w}", justify="center", style="magenta")
    table.add_column("Combination")

    for i in range(1, n_envs, n_weights):
        env = environments[i]
        args = []
        for w in range(n_weights):
            args.append(f'{i + w}')
        args.append(pretty_combination(env['combination']))
        table.add_row(*args)

    print()
    console.print(table)

    # SHOW SIMULATION PROMPT

    exited = False
    while not exited:
        s = input(f"Choose a simulation to view (0-{n_envs - 1} / q to exit): ")
        if s.isdigit() and 0 <= int(s) < len(environments):
            show_simulation(config, 10, closed_edges, environments[int(s)], run_folder)
        elif s in ["q", "Q"]:
            if not keep_output:
                remove_output_folder(run_folder)
            exited = True


def remove_output_folder(run_folder):
    output_folder = os.path.join(run_folder, "output")
    if os.path.exists(output_folder):
        shutil.rmtree(output_folder)


def mysort(z):
    return int(z[0])


if __name__ == '__main__':
    app()

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

import matplotlib.pyplot as plt

app = typer.Typer()


def reference_simulation(gui, config, closed_street, debug):
    return base_simulation(config.absolute(), 0, closed_street, gui=gui, debug=debug)


def closed_street_simulation(gui, config, delay, closed_street, affected, wrong, _progress, task_id, preferred_street,
                             debug):
    return simulate(gui, config, delay, closed_street, preferred_street, affected, wrong, _progress, task_id,
                    keep_running=True, debug=debug,
                    log_duration=False, log_emissions=False, log_statistics=False, log_edgedata=False)


@app.command()
def main(config: Path,
         close: Annotated[Optional[List[str]], typer.Option()] = None,
         graph: Annotated[Optional[List[AvailableData]], typer.Option()] = None,
         # parameters: List[AvailableData] = Argument(default=None),
         show_gui: bool = False, debug: bool = False):
    if config.is_dir():
        print("Config is a directory, should be a file")
        raise typer.Abort()
    elif not config.exists():
        print("The given config doesn't exist")
        raise typer.Abort()

    if not graph:
        parameters = [e for e in list(AvailableData.__members__)]
    else:
        parameters = graph

    concurrent = 1 if show_gui else os.cpu_count()
    delay = "1" if show_gui else "0"

    closed_street = close if close else []

    # FETCH NEIGHOURING EDGES

    pre_result = reference_simulation(show_gui, config.absolute(), closed_street, debug)
    baseline = {p: float(pre_result[p] if len(str(pre_result[p])) > 0 else 0) for p in parameters}
    closed_street_neighbours = pre_result["neighbours"]
    affected = pre_result["affected"]
    wrong = pre_result["wrong"]
    total = pre_result["total"]

    print("[blue]Completed reference simulation")

    # RUN PARALLEL SIMULATIONS

    jobs = []

    num = len(closed_street_neighbours)
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
                            executor.submit(closed_street_simulation, show_gui, config.absolute(), delay, closed_street,
                                            affected, wrong, _progress, task_id, closed_street_neighbours[n], debug))

                    while (n_finished := sum([future.done() for future in jobs])) < len(jobs):
                        all_progress.update(overall_progress_task, completed=n_finished, total=len(jobs))
                        for task_id, update_data in _progress.items():
                            desc = update_data["description"]
                            latest = update_data["progress"]
                            all_progress.update(
                                task_id, description=desc, completed=latest, total=total, visible=latest < total)

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
                x.append(f'{result["pref_street"]} ({result["pref_street_name"]})')
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


if __name__ == '__main__':
    app()

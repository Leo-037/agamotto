import multiprocessing
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from enum import Enum
from pathlib import Path
from typing import Annotated, Optional, List

import typer
from rich import print, progress

from simulation import simulate

if 'SUMO_HOME' in os.environ:
    sys.path.append(os.path.join(os.environ['SUMO_HOME'], 'tools'))

import matplotlib.pyplot as plt

app = typer.Typer()

SAN_FELICE = '43469298#1'
VIALE_ALDINI = [
    # '23288931#6', '23288931#3', '23288931#2', '23288931#1', '23288931#0',
    '23837911#0', '23837911#1', '23837911#3', '292179033#0', '292179033#3', '292179033#4', '292179033#5'
]


class AvailableData(str, Enum):
    duration = 'duration'
    routeLength = 'routeLength'
    departDelay = 'departDelay'
    waitingTime = 'waitingTime'
    speed = 'speed'
    timeloss = 'timeloss'
    totalTime = 'totalTime'
    teleports = 'teleports'
    CO2 = "CO2"
    CO = "CO"
    HC = "HC"
    PMx = "PMx"
    NOx = "NOx"
    fuel = "fuel"
    noise = "noise"

    def __str__(self):
        return self.name


def reference_simulation(program, config, closed_street):
    return simulate(program, config.absolute(), 0, closed_street, _progress=None, task_id=None,
                    description="reference", output_neighbouring_edges=True)


def closed_street_simulation(program, config, delay, closed_street, _progress, task_id, preferred_street):
    return simulate(program, config, delay, closed_street, _progress, task_id,
                    street_is_closed=True,
                    preferred_street=preferred_street,
                    log_duration=False,
                    log_emissions=False,
                    log_statistics=False,
                    log_edgedata=False)


@app.command()
def main(config: Path,
         close: Annotated[Optional[List[str]], typer.Option()] = None,
         graph: Annotated[Optional[List[AvailableData]], typer.Option()] = None,
         # parameters: List[AvailableData] = Argument(default=None),
         show_gui: bool = False):
    if config.is_dir():
        print("Config is a directory")
        raise typer.Abort()
    elif not config.exists():
        print("The config doesn't exist")
        raise typer.Abort()

    if not graph:
        parameters = [e for e in list(AvailableData.__members__)]
    else:
        parameters = graph

    concurrent = 1 if show_gui else 4
    program = "sumo-gui" if show_gui else "sumo"
    delay = "1" if show_gui else "0"

    closed_street = close if close else []

    pre_result = reference_simulation(program, config.absolute(), closed_street)
    closed_street_neighbours = pre_result["neighbours"]
    baseline = {p: float(pre_result[p] if len(str(pre_result[p])) > 0 else 0) for p in parameters}

    print("[blue]Completed reference simulation")

    jobs = []

    num = len(closed_street_neighbours)
    if num > 0:
        with progress.Progress(
                "[progress.description]{task.description}",
                progress.BarColumn(),
                progress.MofNCompleteColumn(),
                progress.TextColumn("•"),
                # "[progress.percentage]{task.percentage:>3.0f}%",
                progress.TimeElapsedColumn(),
        ) as all_progress:
            with multiprocessing.Manager() as manager:
                _progress = manager.dict()
                overall_progress_task = all_progress.add_task("[green]Simulations progress:")

                with ProcessPoolExecutor(max_workers=concurrent) as executor:
                    for n in range(num):
                        task_id = all_progress.add_task(f"task {n}", visible=False, total=None)
                        jobs.append(
                            executor.submit(closed_street_simulation, program, config.absolute(), delay, closed_street,
                                            _progress, task_id, closed_street_neighbours[n]))

                    while (n_finished := sum([future.done() for future in jobs])) < len(jobs):
                        all_progress.update(
                            overall_progress_task, completed=n_finished, total=len(jobs)
                        )
                        for task_id, update_data in _progress.items():
                            desc = update_data["description"]
                            latest = update_data["progress"]
                            total = update_data["total"]
                            all_progress.update(task_id,
                                                description=desc, completed=latest, total=total, visible=latest < total)
            all_progress.update(overall_progress_task,
                                description="All simulations completed", completed=len(jobs), total=len(jobs))

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

        fig = plt.figure(figsize=(12, 6))  # Increase figure size
        fig.canvas.manager.set_window_title(parameter)
        plt.xticks(rotation=45, ha="right")
        plt.scatter(x_vals, y_vals)
        plt.axhline(y=baseline[parameter], color='black', linestyle='--')

        # for i in range(len(y_vals)):
        #     plt.annotate(f'{y_vals[i]}', (i, y_vals[i]), textcoords="offset points", xytext=(0, 7),
        #                  ha='center', fontsize=10, color='blue')

        plt.title(parameter)
        plt.tight_layout()
    plt.show()


if __name__ == '__main__':
    app()

# Agamotto
[**SUMO**](https://sumo.dlr.de/docs/index.html) middleware to simulate various scenarios of traffic given a road closure

## Requirements

Agamotto needs:
 - A complete [**SUMO**](https://sumo.dlr.de/docs/Downloads.php) installation
 - [**python 3.12**](https://www.python.org/downloads/) or greater
 - [**poetry**](https://python-poetry.org/docs/#installation) package manager

## Installation

```
poetry install
```

## Features

 - Automatically performs parallel simulations of different combinations of traffic redirection strategies given the list of closed streets
 - Differentiate which vehicles know about traffic change a priori with configurable weights
 - View all simulations in real time on sumo-gui, with colored edges and vehicles
 - Gather average data for comparison and plot various metrics for all simulations
 - Review any simulation with sumo-gui after all are done executing

## How to use

Run main.py using poetry:
```
poetry run python main.py CONFIG
```
The only required argument is a valid path to a `.sumocfg` file, containing the links to a _network_ and _routes_ files.

A help page is also available:
```
poetry run python main.py --help
```

## Configuration

There are many available options. 

---

#### Close an edge in the simulation environment.  
Use: `--close EDGE_ID`  
Default: `none`  
Multiple: `true`

Example:
```
... main.py CONFIG --close 123456#0 --close 9876543
```

---

#### Generate graph comparing averages of a metric between all simulations
Use: `--graph TYPE`  
Default: `none`  
Multiple: `true`  
Types: `duration`/ `routeLength`/ `waitingTime`/ `speed`/ `timeloss`/ `totalTime`/ `CO2`/ `CO`/ `HC`/ `PMx`/ `NOx`/ `fuel`/ `noise`

Example:
```
... main.py CONFIG --graph duration --graph CO2
```

---

#### Generate complete plot for each simulation for the given metric
Use: `--plot TYPE`  
Default: `none`  
Multiple: `true`  
Types: `summary` / `traffic` / `CO2` / `CO` / `HC` / `NOx` / `PMx` / `fuel` / `electricity` / `noise`

Summary plots vehicles entering the simulation as a curve, while all other metrics are shown as heatmaps on top of the simulation area map.

Example:
```
... main.py CONFIG --plot traffic --plot NOx
```

---

#### Add weights for communicating road closures
Use: `--weight INT1 INT2`  
Default: `(100/0), (0/100), (50/50)`  
Multiple: `true`  

Vehicles in the network are told that a street is closed either beforehand or when reaching its proximity, according to the specified weights. 
If more than one pair is defined, each environment will be simulated for every one of them.   
By default, three weights pairs are defined, but any weight definition will overwrite this.

Example:
```
... main.py CONFIG --weight 80 20 --weight 40 60
```

---

#### Show all simulations on SUMO GUI in sequence
Use: `--show-gui` / `--no-show-gui`  
Default: `--no-show-gui`

Needs SUMO GUI to be installed. No parallelization is available.

Example:
```
... main.py CONFIG --show-gui
```

---

#### Generate debug files
Use: `--debug` / `--no-debug`  
Default: `--no-debug`  

All logs and debug text is redirected by default on devnull. If debug is true, files for each simulation are instead generated in the output folder.

Example:
```
... main.py CONFIG --debug
```

---

#### Keep output files
Use: `--keep-output` / `--no-keep-output`  
Default: `--no-keep-output`  

Each simulation needs to generate some output files to be able to plot any metric. If this option is true, files aren't deleted after the program is done.
Files take up a lot of space, especially for long simulation times or if many combinations where tried.

Example:
```
... main.py CONFIG --keep-output
```

---

#### Prompt the user for a simulation id to show on SUMO GUI
Use: `--viewer` / `--no-viewer`  
Default: `--no-viewer`  

When all graphs are generated the user can be asked for a valid simulation id to open on SUMO GUI.

Example:
```
... main.py CONFIG --viewer
```

---

#### Define the minimum number of simulations to execute on each thread
Use: `--min-sim INT`  
Default: `1`  

Simulations are executed in batches on each available thread. Before a new thread is used, `min-sim` simulations are scheduled on each previous thread.

Example:
```
... main.py --min-sim 3
```

---

#### Define the maximum number of threads to use
Use: `--max-concurrent`  
Default: number of cores on the cpu as per `os.cpucount()`  

In combination with `min-sim`, defines how simulations are distributed on the available threads.

Example:
```
... main.py CONFIG --max-concurrent 6
```

---

## Complete example

```
poetry run python main.py CONFIG --close 43469298#1 --close 43469298#2 --show-gui --debug --keep-output --graph duration --plot CO2 --weight 80 20
```

## Licensing
The code in this project is licensed under [Apache 2.0 license](LICENSE.md).
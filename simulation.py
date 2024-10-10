import random
import os
import sys
from enum import Enum

import traci
import traci.constants as tc

# colors
ORANGE = [255, 170, 0]
RED = [255, 0, 0]
BLUE = [0, 0, 255]
GREEN = [0, 255, 0]
NONE = [0, 0, 0, 0]

# edge types
CLOSED = 0
PREFERRED = 1
SELECTED = 2

# street closed notification strategy
NAVIGATION = 0
SIGN = 1
STRATEGIES = [NAVIGATION, SIGN]


def get_departed(filter_ids=None):
    if filter_ids is None:
        filter_ids = []
    newly_departed_ids = traci.simulation.getDepartedIDList()

    filtered_departed_ids = newly_departed_ids if len(filter_ids) == 0 else set(newly_departed_ids).intersection(
        filter_ids)

    return filtered_departed_ids


def set_vehicle_color(veh_id, color):
    traci.vehicle.setColor(veh_id, color)


def mark_edge_closed(edge_id):
    traci.edge.setParameter(edge_id, "agamotto", CLOSED)


def mark_edge_preferred(edge_id):
    traci.edge.setParameter(edge_id, "agamotto", PREFERRED)


def mark_edge_selected(edge_id):
    traci.edge.setParameter(edge_id, "agamotto", SELECTED)


def end_simulation():
    if traci.isLoaded():
        traci.close()


variables = {
    "CO2": tc.VAR_CO2EMISSION,
    "CO": tc.VAR_COEMISSION,
    "HC": tc.VAR_HCEMISSION,
    "NOx": tc.VAR_NOXEMISSION,
    "PMx": tc.VAR_PMXEMISSION,
    "fuel": tc.VAR_FUELCONSUMPTION,
    "noise": tc.VAR_NOISEEMISSION,
}


def get_sumo_command(config, delay, run_folder, index, gui=False, auto=True, output=True):
    dir_name = os.path.dirname(f'{run_folder}/output/{index}/')
    os.makedirs(dir_name, exist_ok=True)
    command = [
        "sumo-gui" if gui else "sumo",
        '-c', config,
        '--gui-settings-file', './config/agamotto.xml',
        '--delay', str(delay),
        # '--no-step-log',
        # '--verbose',
        '--duration-log.statistics',
        '--no-warnings',
    ]
    if auto:
        command.append('--start')
        command.append('--quit-on-end')
    if output:
        command.append('--emission-output')
        command.append(f'{dir_name}/emission_output.xml')
        command.append('--summary-output')
        command.append(f'{dir_name}/summary_output.xml')
        command.append('--vehroute-output')
        command.append(f'{dir_name}/vehroute_output.xml')
    return command


def batch_simulation(config, delay, closed_edges, environments, thread_id, first_task_id,
                     run_folder, output=True,
                     _progress=None, gui=False, debug=False):
    if debug:
        file_name = f'{run_folder}/sumo/{thread_id}.txt'
        os.makedirs(os.path.dirname(file_name), exist_ok=True)
        sumo_debug = open(file_name, 'w')
    else:
        sumo_debug = open(os.devnull, 'w')

    sys.stdout = sumo_debug

    task_id = first_task_id

    # starts sumo and pipes all output to provided file
    traci.start(get_sumo_command(config, delay, run_folder, task_id, gui, auto=True, output=output), stdout=sumo_debug)

    result = {
        task_id: simulate(0, task_id, thread_id, closed_edges, environments[0], gui, debug, run_folder, _progress)
    }

    for i in range(1, len(environments)):
        task_id += 1
        traci.load(get_sumo_command(config, delay, run_folder, task_id, gui, auto=True, output=output)[1:])
        result[task_id] = simulate(i, task_id, thread_id, closed_edges, environments[i], gui, debug, run_folder,
                                   _progress)

    end_simulation()
    sys.stdout = sys.__stdout__

    return result


def show_simulation(config, delay, closed_edges, environment, run_folder):
    command = get_sumo_command(config, delay, run_folder, -1, gui=True, auto=True, output=False)
    traci.start(command)
    simulate(-1, -1, -1, closed_edges, environment, True, False, run_folder)
    end_simulation()


def reroute_until_correct(veh, combination, gui=False, debug=False):
    attempts = 1
    correct = False
    while not correct:
        if debug:
            print(f'Attempt #{attempts} to route vehicle {veh}')
        correct = True
        route = traci.vehicle.getRoute(veh)
        for redirection in combination:
            if redirection['origin'] in route:
                if redirection['destination'] not in route:
                    traci.vehicle.setVia(veh, redirection['destination'])
                    traci.vehicle.rerouteTraveltime(veh)
                    if gui:
                        # show that vehicle route was affected by deviation
                        set_vehicle_color(veh, ORANGE)

                    correct = False  # route will be checked again
                    break

        if attempts > len(combination) * 2:
            # give up after a while: there's no way to enforce all destinations, keep current route
            if debug:
                print(f'Stopping after attempt #{attempts} to route vehicle {veh}: no way to enforce combination')
            correct = True
        else:
            attempts += 1


def simulate(index, task_id, thread_id, closed_edges, environment, gui, debug, run_folder,
             _progress=None):
    weights = environment['weights']
    combination = environment['combination']
    street_closed = len(weights) + len(combination) > 0

    output = {"id": task_id, "CO2": 0, "CO": 0, "HC": 0, "NOx": 0, "PMx": 0, "fuel": 0, "noise": 0}

    if debug:
        debug_file_name = f'{run_folder}/logs/{task_id}.txt'
        os.makedirs(os.path.dirname(debug_file_name), exist_ok=True)
    else:
        debug_file_name = os.devnull

    with open(debug_file_name, 'w') as debug_file:
        sys.stdout = debug_file
        try:
            subscribed_junction = traci.junction.getIDList()[0]
            traci.junction.subscribeContext(subscribed_junction, tc.CMD_GET_VEHICLE_VARIABLE, 1000000,
                                            variables.values())
            n_steps = 0

            origins = set()
            for redirection in combination:
                origins.add(redirection['origin'])
                if gui:
                    mark_edge_selected(redirection['origin'])
                    mark_edge_preferred(redirection['destination'])

            for edge in closed_edges:
                traci.edge.setDisallowed(edge, 'custom1')
                if gui:
                    mark_edge_closed(edge)

            simulated = 0
            loaded = 0
            sign = []

            while traci.simulation.getMinExpectedNumber() > 0:
                loaded += traci.simulation.getLoadedNumber()
                if street_closed:
                    for vehId in get_departed():

                        route = traci.vehicle.getRoute(vehId)
                        if route[0] in closed_edges:
                            traci.vehicle.remove(vehId)
                            print(f"Removed vehicle {vehId} because its first edge was closed")
                            continue

                        # strategy for road closure communication is chosen
                        # for each vehicle as soon as it is inserted in the simulation.
                        strategy = random.choices(STRATEGIES, weights=weights, k=1)[0]

                        # this user-reserved class disallows the vehicle on any closed edge,
                        # but it will only have effect after rerouting
                        traci.vehicle.setVehicleClass(vehId, 'custom1')

                        # some vehicles know a priori about road closures and deviations
                        if strategy == NAVIGATION:

                            affected = gui and not set(route).isdisjoint(closed_edges)

                            # road closures will be avoided automatically after rerouting,
                            # but road deviations need to be enforced "by hand"
                            reroute_until_correct(vehId, combination, debug)

                            if affected:
                                # show that vehicle route was affected by street closure
                                set_vehicle_color(vehId, RED)

                        if strategy == SIGN:
                            if not set(route).isdisjoint(origins):
                                sign.append(vehId)
                                set_vehicle_color(vehId, BLUE)

                    for vehId in sign:
                        if vehId in traci.vehicle.getIDList():
                            route = traci.vehicle.getRoute(vehId)
                            current = traci.vehicle.getRouteIndex(vehId)
                            # TODO: losing some time on vehicles that are still on the same edge from last step
                            for redirection in combination:
                                if route[current] == redirection['origin']:
                                    traci.vehicle.setVia(vehId, redirection['destination'])
                                    traci.vehicle.rerouteTraveltime(vehId)

                                    if gui:
                                        set_vehicle_color(vehId, GREEN)

                                    break

                            # some combinations may create loops if vehicles can't reach their destination,
                            # so we need to check for duplicate edges in the route
                            new_route = traci.vehicle.getRoute(vehId)

                            # if all edges are unique, the set version of the array has the same length
                            if len(set(new_route)) < len(new_route):
                                sign.remove(vehId)
                                traci.vehicle.remove(vehId)
                                print(f"Removed vehicle {vehId} because it was in a loop")

                        else:
                            sign.remove(vehId)

                # STEP AND UPDATE

                traci.simulationStep()

                sub_results = traci.junction.getContextSubscriptionResults(subscribed_junction)
                if sub_results:
                    for (k, v) in variables.items():
                        new_values = [d[v] for d in sub_results.values()]
                        new_mean = sum(new_values) / len(new_values)
                        output[k] = (n_steps * output[k] + new_mean) / (n_steps + 1)

                n_steps += 1

                # UPDATE PROGRESS ON MAIN THREAD

                if _progress is not None:
                    simulated += traci.simulation.getArrivedNumber()
                    _progress[thread_id] = {
                        'thread_progress': index,
                        'task': task_id,
                        'task_progress': simulated,
                        'task_total': loaded,
                    }

            # RETRIEVE SIMULATION OUTPUT

            output['duration'] = traci.simulation.getParameter("", "device.tripinfo.duration")
            output['routeLength'] = traci.simulation.getParameter("", "device.tripinfo.routeLength")
            output['waitingTime'] = traci.simulation.getParameter("", "device.tripinfo.waitingTime")
            output['speed'] = traci.simulation.getParameter("", "device.tripinfo.speed")
            output['timeloss'] = traci.simulation.getParameter("", "device.tripinfo.timeLoss")
            output['totalTime'] = n_steps * traci.simulation.getDeltaT()

        finally:
            sys.stdout = sys.__stdout__

    return output


class AvailableData(str, Enum):
    duration = 'duration'
    routeLength = 'routeLength'
    waitingTime = 'waitingTime'
    speed = 'speed'
    timeloss = 'timeloss'
    totalTime = 'totalTime'
    CO2 = "CO2"
    CO = "CO"
    HC = "HC"
    PMx = "PMx"
    NOx = "NOx"
    fuel = "fuel"
    noise = "noise"

    def __str__(self):
        return self.name

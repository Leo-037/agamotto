import os
import sys
from enum import Enum

import traci
import traci.constants as tc

# colors
ORANGE = [255, 170, 0]
RED = [255, 0, 0]
NONE = [0, 0, 0, 0]

# edge types
CLOSED = 0
PREFERRED = 1
SELECTED = 2

# street closed notification strategy
NAVIGATION = 0
SIGN = 1


def avoid_edge(veh_id, edge_id):
    traci.vehicle.setAdaptedTraveltime(veh_id, edge_id, float('inf'))
    traci.vehicle.rerouteTraveltime(veh_id)


def prefer_edge(veh_id, edge_id):
    traci.vehicle.setAdaptedTraveltime(veh_id, edge_id, float('-inf'))
    traci.vehicle.rerouteTraveltime(veh_id)


def avoid_multiple(veh_id, edge_list):
    for edge in edge_list:
        avoid_edge(veh_id, edge)


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


def get_neighbouring_edges(edge_id, skip=None):
    if skip is None:
        skip = []

    id_list = []

    origin = traci.edge.getFromJunction(edge_id)
    destination = traci.edge.getToJunction(edge_id)

    id_list.extend(
        edge for edge in traci.junction.getIncomingEdges(origin) if
        'cluster' not in edge and '_' not in edge and edge not in skip)
    id_list.extend(
        edge for edge in traci.junction.getOutgoingEdges(origin) if
        'cluster' not in edge and '_' not in edge and edge not in skip)
    id_list.extend(
        edge for edge in traci.junction.getIncomingEdges(destination) if
        'cluster' not in edge and '_' not in edge and edge not in skip)
    id_list.extend(
        edge for edge in traci.junction.getOutgoingEdges(destination) if
        'cluster' not in edge and '_' not in edge and edge not in skip)

    return id_list


def get_all_neighbouring_edges(edge):
    id_list = []
    if isinstance(edge, list):
        for e in edge:
            id_list.extend(get_neighbouring_edges(e, skip=id_list))
    else:
        id_list = get_neighbouring_edges(edge)

    return list(set(id_list))


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


def prepare_output():
    return {
        "CO2": 0,
        "CO": 0,
        "HC": 0,
        "NOx": 0,
        "PMx": 0,
        "fuel": 0,
        "noise": 0,
    }


def start_simulation(config, delay, debug_file, gui=False, auto=True):
    sys.stdout = debug_file
    command = [
        "sumo-gui" if gui else "sumo",
        '-c', config,
        '--gui-settings-file', './config/agamotto.xml',
        '--delay', str(delay),
        '--no-warnings',
        '--no-step-log',
    ]
    if auto:
        command.append('--start')
        command.append('--quit-on-end')
    if traci.isLoaded():
        traci.load(command[1:])  # omit the name of the program because sumo is already running
    else:
        traci.start(command, stdout=debug_file)  # starts sumo and pipes all output to provided file

    subscribed_junction = traci.junction.getIDList()[0]
    traci.junction.subscribeContext(subscribed_junction, tc.CMD_GET_VEHICLE_VARIABLE, 1000000, variables.values())

    data = {
        'n_steps': 0,
        'subscribed_junction': subscribed_junction
    }
    return data


def step_and_update(output, sim_data):
    traci.simulationStep()

    sub_results = traci.junction.getContextSubscriptionResults(sim_data['subscribed_junction'])
    if sub_results:
        for (k, v) in variables.items():
            new_values = [d[v] for d in sub_results.values()]
            new_mean = sum(new_values) / len(new_values)
            output[k] = (sim_data['n_steps'] * output[k] + new_mean) / (sim_data['n_steps'] + 1)

    sim_data['n_steps'] += 1


def get_simulation_output(output, sim_data):
    output['duration'] = traci.simulation.getParameter("", "device.tripinfo.duration")
    output['routeLength'] = traci.simulation.getParameter("", "device.tripinfo.routeLength")
    output['departDelay'] = traci.simulation.getParameter("", "device.tripinfo.departDelay")
    output['waitingTime'] = traci.simulation.getParameter("", "device.tripinfo.waitingTime")
    output['speed'] = traci.simulation.getParameter("", "device.tripinfo.speed")
    output['timeloss'] = traci.simulation.getParameter("", "device.tripinfo.timeLoss")
    output['teleports'] = traci.simulation.getParameter("", "stats.teleports.total")
    output['totalTime'] = sim_data['n_steps'] * traci.simulation.getDeltaT()


def base_simulation(config, delay, closed_edges, gui=False, debug=False):
    output = prepare_output()

    with open(f'./logs/debug/base.txt' if debug else os.devnull, 'w') as debug_file:
        try:
            sim_data = start_simulation(config, delay, debug_file, gui=gui)

            vehicles = []
            affected = []
            wrong = []

            closed_edges = set(closed_edges)

            while traci.simulation.getMinExpectedNumber() > 0:
                for vehId in get_departed():
                    vehicles.append(vehId)
                    route = traci.vehicle.getRoute(vehId)

                    if set(route).intersection(closed_edges):
                        set_vehicle_color(vehId, ORANGE)
                        affected.append(vehId)

                    # for edge in closed_edges:
                    #     if vehId in affected or vehId in wrong:
                    #         # ignore remaining edges if vehicle was already marked as affected
                    #         break
                    #
                    #     if route[0] == edge or route[-1] == edge:
                    #         # vehicle should be removed because route starts or ends with a closed edge
                    #         wrong.append(vehId)
                    #     elif edge in route:
                    #         set_vehicle_color(vehId, RED)
                    #         affected.append(vehId)

                step_and_update(output, sim_data)

            get_simulation_output(output, sim_data)

            end_simulation()

            output['affected'] = affected
            output['wrong'] = wrong
            output['total'] = len(vehicles)

        finally:
            sys.stdout = sys.__stdout__

    return output


def simulate(gui: bool, config, delay, closed_edges, environment, affected, wrong, task_id,
             _progress=None, debug=False, keep_running=False, auto=True,
             log_duration=False, log_emissions=False, log_statistics=False, log_edgedata=False
             ):
    strategy = environment['strategy']
    combination = environment['combination']

    output = prepare_output()
    output["id"] = task_id

    with open(f'./logs/debug/{task_id}.txt' if debug else os.devnull, 'w') as debug_file:
        try:
            sim_data = start_simulation(config, delay, debug_file, gui=gui, auto=auto)

            output["pref_street"] = ""
            output['pref_street_name'] = ""
            task_description = ""
            for redirection in combination:
                preferred_street = redirection['destination']
                preferred_street_name = traci.edge.getStreetName(preferred_street)

                output["pref_street"] += preferred_street + " "
                output['pref_street_name'] += preferred_street_name + " "
                task_description += f'{preferred_street} '
                if gui:
                    mark_edge_selected(redirection['origin'])
                    mark_edge_preferred(preferred_street)

            for edge in closed_edges:
                if strategy == NAVIGATION:
                    # close the streets in the first step if all vehicles know about street closure
                    traci.edge.setAllowed(edge, 'authority')  # closed to regular traffic
                if gui:
                    mark_edge_closed(edge)

            simulated = 0

            to_notify = []

            while traci.simulation.getMinExpectedNumber() > 0:
                for vehId in get_departed():
                    if vehId in affected:  # route contains a closed edge
                        if gui:
                            set_vehicle_color(vehId, ORANGE)

                        if strategy == NAVIGATION:
                            for redirection in combination:
                                route = traci.vehicle.getRoute(vehId)
                                if redirection['origin'] in route:
                                    if gui:
                                        set_vehicle_color(vehId, RED)
                                    traci.vehicle.setVia(vehId, redirection['destination'])
                                    traci.vehicle.rerouteTraveltime(vehId)
                                    break
                        elif strategy == SIGN:
                            to_notify.append(vehId)
                    else:
                        if gui:
                            # hides cars not affected by street closure
                            set_vehicle_color(vehId, NONE)

                if strategy == SIGN:
                    for redirection in combination:
                        for vehId in traci.edge.getLastStepVehicleIDs(redirection['origin']):
                            # TODO: this doesn't account for vehicles whose first edge is an origin/closed edge
                            if vehId in to_notify:
                                if gui:
                                    set_vehicle_color(vehId, RED)
                                avoid_multiple(vehId, closed_edges)
                                traci.vehicle.setVia(vehId, redirection['destination'])
                                traci.vehicle.rerouteTraveltime(vehId)
                                to_notify.remove(vehId)
                                break

                # TODO: for both strategies, check the route of each vehicle until no redirection is needed ?
                # TODO: change simulation management by keeping track of all vehicles currently in simulation ?

                step_and_update(output, sim_data)

                simulated += traci.simulation.getArrivedNumber()
                if _progress is not None:
                    _progress[task_id] = {"progress": simulated}

            get_simulation_output(output, sim_data)

            if not keep_running:
                end_simulation()

        finally:
            sys.stdout = sys.__stdout__

    return output


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

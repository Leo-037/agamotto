import os
import subprocess
import sys
from functools import partial

import contextily as cx
import geopandas as gpd
import pandas as pd
import sumolib
from lxml import etree
from matplotlib import pyplot as plt
from shapely.geometry import Polygon

SUMO_HOME = os.environ.get("SUMO_HOME", None)
SUMO_TOOLS = os.path.join(SUMO_HOME, "tools")
sys.path.append(SUMO_TOOLS)


class Plotter:
    parser = etree.XMLParser(recover=True)
    summary_file_name = "summary_output.xml"
    emission_file_name = "emission_output.xml"

    def __init__(self, run_folder, network_file, charts_dir_name='charts'):
        self.run_folder = run_folder
        self.net_file = network_file
        self.simulation_network = sumolib.net.readNet(network_file)
        self.grid_taz_file = self.generate_network_grid()
        self.grid_gdf = self.load_grid_gdf()
        self.charts_dir = os.path.join(run_folder, charts_dir_name)
        os.makedirs(self.charts_dir, exist_ok=True)

    def parse_tazs_xml(self, xml_file):
        root = etree.parse(xml_file, parser=self.parser).getroot()
        taz_list = []

        for taz_element in root.findall("taz"):
            shape = taz_element.get("shape")
            shapes = ",".join(str(shape).split(" ")).split(",")
            shapes = [float(i) for i in shapes]
            shapes = [shapes[i:i + 2] for i in range(0, len(shapes), 2)]
            shapes = [self.simulation_network.convertXY2LonLat(i[0], i[1]) for i in shapes]

            shapes = Polygon(shapes)

            taz_list.append(shapes)

        gdf = gpd.GeoDataFrame(taz_list, columns=["geometry"], geometry="geometry", crs=4326)
        gdf["grid_geom"] = gdf["geometry"]

        return gdf

    def parse_summary_xml(self, xml_file):
        root = etree.parse(xml_file, parser=self.parser)

        # Initialize lists to store parsed data
        time_list = []
        loaded_list = []
        inserted_list = []
        running_list = []
        waiting_list = []
        ended_list = []
        arrived_list = []
        collisions_list = []
        teleports_list = []
        halting_list = []
        stopped_list = []
        mean_waiting_time_list = []
        mean_travel_time_list = []
        mean_speed_list = []
        mean_speed_relative_list = []
        duration_list = []

        # Extract data from each <step> element and append to the corresponding lists
        for step in root.findall('step'):
            time_list.append(float(step.attrib['time']))
            loaded_list.append(int(step.attrib['loaded']))
            inserted_list.append(int(step.attrib['inserted']))
            running_list.append(int(step.attrib['running']))
            waiting_list.append(int(step.attrib['waiting']))
            ended_list.append(int(step.attrib['ended']))
            arrived_list.append(int(step.attrib['arrived']))
            collisions_list.append(int(step.attrib['collisions']))
            teleports_list.append(int(step.attrib['teleports']))
            halting_list.append(int(step.attrib['halting']))
            stopped_list.append(int(step.attrib['stopped']))
            mean_waiting_time_list.append(float(step.attrib['meanWaitingTime']))
            mean_travel_time_list.append(float(step.attrib['meanTravelTime']))
            mean_speed_list.append(float(step.attrib['meanSpeed']))
            mean_speed_relative_list.append(float(step.attrib['meanSpeedRelative']))
            duration_list.append(int(step.attrib['duration']))

        # Create a DataFrame from the extracted data
        df = pd.DataFrame({
            'Time': time_list,
            'Loaded': loaded_list,
            'Inserted': inserted_list,
            'Running': running_list,
            'Waiting': waiting_list,
            'Ended': ended_list,
            'Arrived': arrived_list,
            'Collisions': collisions_list,
            'Teleports': teleports_list,
            'Halting': halting_list,
            'Stopped': stopped_list,
            'MeanWaitingTime': mean_waiting_time_list,
            'MeanTravelTime': mean_travel_time_list,
            'MeanSpeed': mean_speed_list,
            'MeanSpeedRelative': mean_speed_relative_list,
            'Duration': duration_list
        })

        return df

    def parse_emission_data(self, xml_file):
        tree = etree.parse(xml_file, parser=self.parser)
        root = tree.getroot()

        rows = []
        for timestep_elem in root.findall('timestep'):
            time = float(timestep_elem.get('time'))

            for vehicle_elem in timestep_elem.findall('vehicle'):
                vehicle_data = {
                    'time': time,
                    'vehicle_id': vehicle_elem.get('id'),
                    'eclass': vehicle_elem.get('eclass'),
                    'CO2': float(vehicle_elem.get('CO2')),
                    'CO': float(vehicle_elem.get('CO')),
                    'HC': float(vehicle_elem.get('HC')),
                    'NOx': float(vehicle_elem.get('NOx')),
                    'PMx': float(vehicle_elem.get('PMx')),
                    'fuel': float(vehicle_elem.get('fuel')),
                    'electricity': float(vehicle_elem.get('electricity')),
                    'noise': float(vehicle_elem.get('noise')),
                    'route': vehicle_elem.get('route'),
                    'type': vehicle_elem.get('type'),
                    'waiting': float(vehicle_elem.get('waiting')),
                    'lane': vehicle_elem.get('lane'),
                    'pos': float(vehicle_elem.get('pos')),
                    'speed': float(vehicle_elem.get('speed')),
                    'angle': float(vehicle_elem.get('angle')),
                    'lat': float(
                        self.simulation_network.convertXY2LonLat(float(vehicle_elem.get('x')),
                                                                 float(vehicle_elem.get('y')))[1]),
                    'lon': float(
                        self.simulation_network.convertXY2LonLat(float(vehicle_elem.get('x')),
                                                                 float(vehicle_elem.get('y')))[0])
                }
                rows.append(vehicle_data)

        gdf = gpd.GeoDataFrame(rows,
                               geometry=gpd.points_from_xy([row['lon'] for row in rows], [row['lat'] for row in rows]),
                               crs="4326")
        return gdf

    def generate_network_grid(self, grid_width='150'):
        """ Divides the network in grid (150m x 150m) """

        grid_filename = os.path.join(self.run_folder, "output", "grid_district.taz.xml")

        grid_options = ["python", os.path.join(SUMO_TOOLS, "district", "gridDistricts.py")]
        grid_options += ["-n", os.path.abspath(self.net_file)]
        grid_options += ["-o", os.path.abspath(grid_filename)]
        grid_options += ["-w", grid_width]
        subprocess.call(grid_options, cwd=self.run_folder)

        return grid_filename

    def load_grid_gdf(self):
        return self.parse_tazs_xml(self.grid_taz_file)


class SimPlotter:
    CONTEXTILY_PROVIDER = cx.providers.OpenStreetMap.Mapnik

    def __init__(self, p: Plotter, index, organize="by_metric"):
        self.plotter = p
        self.index = index
        self.sim_folder = f'{p.run_folder}/output/{index}'
        self.gdf, self.point_in_grid = self.load_point_in_grid()
        self.organization = organize
        self.plot_methods = {
            'summary': self.generate_summary_plot,
            'traffic': self.generate_traffic_plot,
            'CO2': partial(self.generate_emission_plot, field='CO2', label='CO2 emission rate per tile (mg/s)'),
            'CO': partial(self.generate_emission_plot, field='CO', label='CO emission rate per tile'),
            'HC': partial(self.generate_emission_plot, field='HC', label='HC emission rate per tile'),
            'NOx': partial(self.generate_emission_plot, field='NOx', label='NOx emission rate per tile'),
            'PMx': partial(self.generate_emission_plot, field='PMx', label='PMx emission rate per tile'),
            'fuel': partial(self.generate_emission_plot, field='fuel', label='fuel emission rate per tile'),
            'electricity': partial(self.generate_emission_plot, field='electricity',
                                   label='electricity emission rate per tile'),
            'noise': partial(self.generate_emission_plot, field='noise', label='noise emission rate per tile'),
        }

    def available_plots(self):
        return list(self.plot_methods.keys())

    def plot(self, kind):
        if kind in self.plot_methods:
            self.plot_methods[kind]()
        else:
            raise ValueError(f"Plot kind '{kind}' is not supported.")

    def img_prefix(self):
        return f'{self.index}'

    def img_name(self, metric, *args):
        name = ""
        for arg in args:
            name += f'_{arg}'

        if self.organization == "by_metric":
            file_name = f'{metric}/{self.img_prefix()}{name}.png'
        else:  # self.organization == "by_run":
            file_name = f'{self.img_prefix()}/{metric}{name}.png'

        file_path = os.path.join(self.plotter.charts_dir, file_name)
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        return file_path

    def load_point_in_grid(self):
        xml_file_path = os.path.join(self.sim_folder, self.plotter.emission_file_name)
        gdf = self.plotter.parse_emission_data(xml_file_path)
        gdf = gdf.to_crs(epsg=4326)

        return gdf, gdf.sjoin(self.plotter.grid_gdf, how="inner").reset_index(drop=True)

    def generate_summary_plot(self):
        xml_file_path = os.path.join(self.sim_folder, self.plotter.summary_file_name)
        summary_df = self.plotter.parse_summary_xml(xml_file_path)
        summary_df = summary_df.set_index("Time")

        temp = summary_df
        temp["SumHalting"] = summary_df["Halting"].sum()
        temp["SumCollisions"] = summary_df["Collisions"].sum()
        temp["SumStopped"] = summary_df["Stopped"].sum()
        temp["SumTeleports"] = summary_df["Teleports"].sum()

        summary_df = summary_df[["Running", "Waiting", "Teleports"]]
        ax = summary_df.plot()

        ax.set_xlabel("Simulation time (s)")
        ax.set_ylabel("Number of vehicles")
        plt.legend(ncol=3, bbox_to_anchor=(1.1, 1.2))
        plt.tight_layout()
        plt.savefig(self.img_name('summary'))

    def generate_traffic_plot(self):
        vehicle_density = self.point_in_grid.groupby(by=["grid_geom"])["vehicle_id"].nunique().reset_index()
        vehicle_density = gpd.GeoDataFrame(vehicle_density, geometry="grid_geom")
        vehicle_density = vehicle_density.set_crs(epsg=4326)

        vehicle_density = vehicle_density.to_crs(epsg=3857)
        legend = dict(label='Number of vehicles per tile')
        ax = vehicle_density.plot(column="vehicle_id", legend=True, alpha=0.7, cmap="Reds", legend_kwds=legend, vmin=0,
                                  vmax=100)
        cx.add_basemap(ax, attribution_size=0, source=self.CONTEXTILY_PROVIDER, alpha=0.7)
        ax.set_axis_off()

        plt.tight_layout()
        plt.savefig(self.img_name('traffic'))

    def generate_emission_plot(self, field, label, colormap="Greens"):
        column = f"{field}_average"
        emission_results = self.point_in_grid.groupby(by="grid_geom")[field].sum().reset_index()
        emission_results[column] = emission_results[field] / self.gdf["time"].iloc[-1]
        emission_results = gpd.GeoDataFrame(emission_results, crs=self.gdf.crs, geometry="grid_geom")

        emission_results = emission_results.to_crs(epsg=3857)
        legend = dict(label=label)
        ax = emission_results.plot(column=column, legend=True, alpha=0.7, cmap=colormap, legend_kwds=legend)
        cx.add_basemap(ax, attribution_size=0, source=self.CONTEXTILY_PROVIDER, alpha=0.7)
        ax.set_axis_off()

        plt.tight_layout()
        plt.savefig(self.img_name(field))

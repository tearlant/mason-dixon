import os
import geopandas as gpd

from enum import Enum
from functools import total_ordering

from . import coordinate_utility
from .coordinate_utility import display_wgs_string
from .geometric import wrap_polygon


# A Primary city is defined as either a capital, a world city, part of a megalopolis, or population 10 million.
@total_ordering
class CityTypes(Enum):
    PRIMARY = 1
    OVER5MIL = 2
    OVER2p5MIL = 3
    OVER1MIL = 4
    OVER500K = 5
    OVER250K = 6
    OVER100K = 7
    OVER50K = 8
    UNDER50K = 9

    def __lt__(self, other):
        if self.__class__ is other.__class__:
            return self.value < other.value
        if type(other) is int:
            return self.value < other
        return NotImplemented

    def __eq__(self, other):
        if self.__class__ is other.__class__:
            return self.value == other.value
        if type(other) is int:
            return self.value == other
        return NotImplemented


def classify_city(population, is_capital, is_global, is_mega):
    if is_capital == 1 or is_global == 1 or is_mega == 1:
        return CityTypes.PRIMARY
    elif population >= 1e7:
        return CityTypes.PRIMARY
    elif population >= 5e6:
        return CityTypes.OVER5MIL
    elif population >= 2.5e6:
        return CityTypes.OVER2p5MIL
    elif population >= 1e6:
        return CityTypes.OVER1MIL
    elif population >= 5e5:
        return CityTypes.OVER500K
    elif population >= 2.5e5:
        return CityTypes.OVER250K
    elif population >= 1e5:
        return CityTypes.OVER100K
    elif population >= 5e4:
        return CityTypes.OVER50K
    else:
        return CityTypes.UNDER50K


class DataProvider:

    def __init__(self, rate_fn):
        # We want the server to have WGS coordinates (for the web API calls it must make)
        # and the client to have Web Mercator coordinates (for plotting libraries).
        # The Natural Earth (raw) data is in WGS.
        self.region_file_loc = os.path.join('geographic_data', 'cache', 'regions_test.geojson')
        self.region_dataframe = gpd.read_file(self.region_file_loc)
        self.region_dataframe['mercator'] = self.region_dataframe.apply(lambda x: wrap_polygon(
            coordinate_utility.multipolygon_to_mercator(x['geometry'])), axis=1)

        # For convenience (and compatibility with certain library API functions), there are
        # separate 'cities' frames, with the 'geometry' columns in the different coordinate systems.
        self.cities_file_loc = os.path.join('geographic_data', 'cache', 'cities_test.geojson')
        self.cities_dataframe_wgs = gpd.read_file(self.cities_file_loc)
        self.cities_dataframe_wgs['index'] = self.cities_dataframe_wgs.index
        self.cities_dataframe_wgs['rate'] = self.cities_dataframe_wgs.apply(lambda city: rate_fn(city['geometry']), axis=1)
        self.cities_dataframe_wgs['display_string'] = self.cities_dataframe_wgs.apply(lambda x: f"{x['name']} {display_wgs_string(x['geometry'])}", axis=1)

        self.cities_dataframe_mercator = self.cities_dataframe_wgs.copy(True)
        self.cities_dataframe_mercator['mercator'] = self.cities_dataframe_mercator.apply(
            lambda city: coordinate_utility.point_to_mercator(city['geometry']), axis=1)
        self.cities_dataframe_mercator = self.cities_dataframe_mercator.set_geometry('mercator', drop=True)
        self.cities_dataframe_mercator['updates'] = self.cities_dataframe_mercator.apply(lambda city: 0, axis=1)

    def get_region_data(self):
        return self.region_dataframe.copy(deep=True)

    def get_cities_wgs(self):
        return self.cities_dataframe_wgs.copy(deep=True)

    def get_cities_mercator(self):
        return self.cities_dataframe_mercator.copy(deep=True)


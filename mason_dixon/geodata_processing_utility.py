import geopandas as gpd
import os

from .special_regions import keep_unit, get_unit_group
from .geometric import wrap_polygon
from .data_provider import classify_city


# TODO: This currently has some paths hard-coded, and requires the Natural Earth datasets It needs to be made dynamic.
def load_regions_into_json(still_run_if_cached):
    region_file_loc = os.path.join('geographic_data', 'cache', 'regions_test.geojson')

    if still_run_if_cached and os.path.exists(region_file_loc):
        os.remove(region_file_loc)

    if os.path.exists(region_file_loc):
        return

    zipfile = "zip://./geographic_data/ne_10m_admin_0_map_subunits.zip"
    subunits = gpd.read_file(zipfile)
    subunits = subunits.sort_values('SOVEREIGNT')
    subunits = subunits[['GEOUNIT', 'SOVEREIGNT', 'geometry']]

    # Remove uninhabited regions
    subunits.loc[:, 'keep'] = subunits.apply(lambda x: keep_unit(x['GEOUNIT']), axis=1)
    subunits = subunits.loc[subunits['keep'], subunits.columns != 'keep']

    # Group certain subunits (for example, Belgium is encoded as Walloon and Flemish regions)
    subunits['group'] = subunits.apply(lambda x: get_unit_group(x['GEOUNIT']), axis=1)

    aggregated = subunits.dissolve(by='group').reset_index()
    aggregated.rename(columns={'group': 'UNIT'}, inplace=True)
    aggregated['wrapped'] = aggregated.apply(lambda x: wrap_polygon(x['geometry']), axis=1)

    aggregated = aggregated.loc[:, aggregated.columns != 'geometry']
    aggregated.set_geometry('wrapped', inplace=True)

    aggregated.to_file(region_file_loc, driver='GeoJSON', encoding='utf-8')


def load_cities_into_json(still_run_if_cached):
    cities_file_loc = os.path.join('geographic_data', 'cache', 'cities_test.geojson')

    if still_run_if_cached and os.path.exists(cities_file_loc):
        os.remove(cities_file_loc)

    if os.path.exists(cities_file_loc):
        return

    zipfile = "zip://./geographic_data/ne_10m_populated_places_simple.zip"
    cities = gpd.read_file(zipfile)

    cities = cities.sort_values(['pop_max'], ascending=[False])
    cities['category'] = cities.apply(lambda x: classify_city(x.pop_max, x.adm0cap, x.worldcity, x.megacity).value, axis=1)

    cities.to_file(cities_file_loc, driver='GeoJSON', encoding='utf-8')


load_regions_into_json(True)
load_cities_into_json(True)

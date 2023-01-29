import logging
import pickle

import asyncio
from shapely.geometry import Polygon, Point
from mason_dixon import municipal_data_utility as mun_util, coordinate_utility


def get_cached_indices_for_frame(city_cache, lon_wgs, lat_wgs, aspect_ratio, zoom):
    # city_array and region_array have their geometry values in WGS84 coordinates to use the Travel APIs
    # zoom needs to determine the critical population values
    frame_size = (zoom, zoom / aspect_ratio)

    # Server side, pull data for cities around the outside of the frame to anticipate zooming and panning.
    upper_left_wgs = (lon_wgs - frame_size[0], lat_wgs + frame_size[1])
    lower_right_wgs = (lon_wgs + (2 * frame_size[0]), upper_left_wgs[1] - (2 * frame_size[1]))

    lon_point_list = [upper_left_wgs[0], lower_right_wgs[0], lower_right_wgs[0], upper_left_wgs[0]]
    lat_point_list = [upper_left_wgs[1], upper_left_wgs[1], lower_right_wgs[1], lower_right_wgs[1]]
    frame_geometry = Polygon(zip(lon_point_list, lat_point_list))

    little_population, big_population = mun_util.map_zoom_to_population(zoom)
    indices = [x for x in city_cache if city_cache[x]['geometry'].within(frame_geometry) and city_cache[x]['population'] >= little_population]
    return indices


def get_new_city_cache_wgs(city_data):
    data = zip(city_data['rate'], city_data['index'], city_data['geometry'], city_data['pop_max'])
    return {
        index: {
            'index': index,
            'rate': rate,
            'geometry': geom,
            'population': pop,
            'update_counter': 0
        } for rate, index, geom, pop in data
    }


def get_city_info(city):
    res = dict()
    res['update_counter'] = city['update_counter']
    res['rate'] = city['rate']
    res['index'] = city['index']
    return res


async def request_city_data_from_database(city_cache, indices, rate_fn, update_counter):
    # city_array and region_array have their geometry values in WGS84 coordinates to use the Travel APIs
    # zoom needs to determine the critical population values
    cities = {x: city_cache[x] for x in city_cache if x in indices}

    tasks = [get_city_rate(cities[index], update_counter, rate_fn) for index in cities]
    rates = await asyncio.gather(*tasks)

    for city in rates:
        city_cache[city['index']]['rate'] = city['rate']
        city_cache[city['index']]['update_counter'] = update_counter


async def get_city_rate(city, update_counter, rate_fn):
    if city['update_counter'] >= update_counter:
        return {'index': city['index'], 'rate': city['rate']}

    rate = await rate_fn(city)
    return {'index': city['index'], 'rate': rate}


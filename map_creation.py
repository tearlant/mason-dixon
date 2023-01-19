import logging
import pickle

from shapely.geometry import Polygon, Point
from geographic_engine import municipal_data_utility as mun_util, coordinate_utility


def request_city_data_from_server(city_array, lon_wgs, lat_wgs, aspect_ratio, zoom, request_id, session_guid, ws_conn):
    # city_array and region_array have their geometry values in WGS84 coordinates to use the Travel APIs
    # zoom needs to determine the critical population values

    frame_size = (zoom, zoom / aspect_ratio)
    upper_left_wgs = (lon_wgs, lat_wgs)
    lower_right_wgs = (upper_left_wgs[0] + frame_size[0], upper_left_wgs[1] - frame_size[1])

    upper_left_merc = coordinate_utility.point_to_mercator(Point(upper_left_wgs[0], upper_left_wgs[1]))
    lower_right_merc = coordinate_utility.point_to_mercator(Point(lower_right_wgs[0], lower_right_wgs[1]))

    lon_point_list = [upper_left_merc.x, lower_right_merc.x, lower_right_merc.x, upper_left_merc.x]
    lat_point_list = [upper_left_merc.y, upper_left_merc.y, lower_right_merc.y, lower_right_merc.y]

    logging.debug("Requesting municipal data (client side). Corners of the map:")
    for elt in zip(lon_point_list, lat_point_list):
        logging.debug(str(elt))

    frame_geometry = Polygon(zip(lon_point_list, lat_point_list))

    # little_population is needed server side.
    little_population, big_population = mun_util.map_zoom_to_population(zoom)

    # In the prototype, there is a lambda that maps a City (Point) geometry to a number, i.e. the average cost to visit.
    # Unlike prototype, this needs to be broken apart into get_cities_within_geometry, then a ws call.
    filtered_cities = mun_util.get_cities_within_geometry(frame_geometry, city_array, little_population, [])

    payload = dict()
    payload['upper_left_wgs'] = upper_left_wgs
    payload['lower_right_wgs'] = lower_right_wgs
    payload['min_population'] = little_population
    payload['method'] = 'average'
    payload['request_id'] = request_id
    payload['indices'] = filtered_cities['index']
    payload['session_guid'] = session_guid
    ws_conn.write_message(pickle.dumps(payload), binary=True)


# TODO: Everything needs to be moved to another file once this is working
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

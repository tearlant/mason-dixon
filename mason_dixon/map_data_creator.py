import os
import pickle

from shapely.geometry import Polygon
from .geometric import wrap_polygon, conditionally_split_multipolygon, unroll_multipolygon
from . import municipal_data_utility as mun_util


def get_box_around_city(frame_geometry, city_box_height, city_box_width, point_geometry, region_geometry):
    point_lon = point_geometry.xy[0][0]
    point_lat = point_geometry.xy[1][0]

    lon_spacing = 0.5 * city_box_width
    lat_spacing = 0.5 * city_box_height

    box_longitudes = [point_lon - lon_spacing, point_lon + lon_spacing, point_lon + lon_spacing,
                      point_lon - lon_spacing]
    box_latitudes = [point_lat + lat_spacing, point_lat + lat_spacing, point_lat - lat_spacing, point_lat - lat_spacing]

    init_geom = Polygon(zip(box_longitudes, box_latitudes))
    res1 = init_geom.intersection(frame_geometry)

    # region_geometry may be a multipolygon
    res = res1.intersection(region_geometry)

    return wrap_polygon(res)


# Given an outer frame, a size of boxes, an array of cities, and a region Geometry, it splits the Geometry
# into rectangular subregions, with smaller boxes around the cities. rate_rule is a lambda that takes a
# MultiPolygon and an array of cities, and aggregates the data into a single value. (It has to happen
# at this layer because the multipolygons are created dynamically on the fly, for example as the user zooms
# and pans)
def get_boxes_around_cities(outer_frame_geometry, box_factor, city_box_height, city_box_width, city_array,
                            region_geometry_multipolygon, name, rate_rule, min_pop_for_boxes):
    max_size = outer_frame_geometry.area / box_factor

    cities_in_region = city_array[city_array['geometry'].within(region_geometry_multipolygon)]
    cities_in_region = cities_in_region[cities_in_region['pop_max'] >= min_pop_for_boxes]

    boxes = []
    remainder = region_geometry_multipolygon

    for city_geometry in cities_in_region['geometry']:
        box = get_box_around_city(outer_frame_geometry, city_box_height, city_box_width, city_geometry, remainder)
        boxes.append(box)
        remainder = wrap_polygon(remainder.difference(box))

    remainder = conditionally_split_multipolygon(remainder, max_size)

    longitudes = [list(polygon.exterior.coords.xy[0]) for multipolygon in boxes for polygon in multipolygon.geoms]
    longitudes.extend(
        [list(polygon.exterior.coords.xy[0]) for multipolygon in remainder for polygon in multipolygon.geoms]
    )

    latitudes = [list(polygon.exterior.coords.xy[1]) for multipolygon in boxes for polygon in multipolygon.geoms]
    latitudes.extend(
        [list(polygon.exterior.coords.xy[1]) for multipolygon in remainder for polygon in multipolygon.geoms]
    )

    names = [name for multipolygon in boxes for polygon in multipolygon.geoms]
    names.extend([name for multipolygon in remainder for polygon in multipolygon.geoms])

    rates = []

    def rr(multipoly):
        return rate_rule(multipoly, city_array)

    for multipolygon in boxes:
        rate = rr(multipolygon)
        for polygon in multipolygon.geoms:
            rates.append(rate)

    for multipolygon in remainder:
        rate = rr(multipolygon)
        for polygon in multipolygon.geoms:
            # rates.append(maximum)
            rates.append(rate)

    return longitudes, latitudes, names, rates


# A version of the previous function meant for Bokeh's MultiPolygons glyphs
def get_boxes_around_cities_mp(outer_frame_geometry, box_factor, city_box_height, city_box_width, city_array,
                               region_geometry_multipolygon, name, rate_rule, min_pop_for_boxes):
    max_size = outer_frame_geometry.area / box_factor

    cities_in_region = city_array[city_array['geometry'].within(region_geometry_multipolygon)]
    cities_in_region = cities_in_region[cities_in_region['pop_max'] >= min_pop_for_boxes]

    boxes = []
    remainder = region_geometry_multipolygon

    for city_geometry in cities_in_region['geometry']:
        box = get_box_around_city(outer_frame_geometry, city_box_height, city_box_width, city_geometry, remainder)
        boxes.append(box)
        remainder = wrap_polygon(remainder.difference(box))

    remainder = conditionally_split_multipolygon(remainder, max_size)

    def rr(multipoly):
        return rate_rule(multipoly, city_array)

    longitudes = [unroll_multipolygon(multipolygon, 0) for multipolygon in boxes]
    longitudes.extend([unroll_multipolygon(multipolygon, 0) for multipolygon in remainder])
    latitudes = [unroll_multipolygon(multipolygon, 1) for multipolygon in boxes]
    latitudes.extend([unroll_multipolygon(multipolygon, 1) for multipolygon in remainder])
    names = [name for _ in boxes]
    names.extend([name for _ in remainder])
    rates = [rr(multipolygon) for multipolygon in boxes]
    rates.extend([rr(multipolygon) for multipolygon in remainder])

    return longitudes, latitudes, names, rates


# TODO: Debug. The prototype was in WGS84, but this is completely in Mercator
# This is called during a periodic callback when an update is needed (different from the prototype)
# so city_array is no longer pre-filtered.
def render_full_map(upper_left_merc, lower_right_merc, box_factor, city_array, region_table, rate_rule,
                    city_box_proportion, use_cache):  # , min_population=500000):
    # The Mercator values need to be returned for certain functions in bokeh.
    cache_file_loc = os.path.join('geographic_data', 'cache', 'saved_map_data.pickle')
    if use_cache and os.path.exists(cache_file_loc):
        with open(cache_file_loc, 'rb') as handle:
            cached = pickle.load(handle)
            return cached['data'], cached['city_data']

    little_population, big_population = mun_util.map_mercator_window_to_population(upper_left_merc, lower_right_merc)

    lon_point_list_merc = [upper_left_merc.x, lower_right_merc.x, lower_right_merc.x, upper_left_merc.x]
    lat_point_list_merc = [upper_left_merc.y, upper_left_merc.y, lower_right_merc.y, lower_right_merc.y]

    city_box_height = abs(city_box_proportion * (upper_left_merc.y - lower_right_merc.y))
    city_box_width = abs(city_box_proportion * (upper_left_merc.x - lower_right_merc.x))

    # TODO: Could optimize this with caching
    # TODO: Remove commented code once tested
    frame_geometry_merc = Polygon(zip(lon_point_list_merc, lat_point_list_merc))
    roi = region_table[region_table['mercator'].intersects(frame_geometry_merc)]
    roi['mercator'] = roi.apply(lambda x: wrap_polygon(x['mercator'].intersection(frame_geometry_merc)), axis=1)

    filtered_array = mun_util.get_cities_within_geometry(frame_geometry_merc, city_array, little_population, ['display_string', 'rate'])
    filtered_array['formatted'] = filtered_array.apply(lambda x: ("%.2f" % x['rate']), axis=1)

    # TODO: Make labels cities, not countries
    longitudes = []
    latitudes = []
    labels = []
    rates = []

    # TODO: Factor this out
    for index, row in roi.iterrows():
        row_lons, row_lats, row_names, row_rates = \
            get_boxes_around_cities_mp(frame_geometry_merc, box_factor, city_box_height, city_box_width, filtered_array,
                                       row['mercator'], row['SOVEREIGNT'], rate_rule, big_population)

        longitudes.extend(row_lons)
        latitudes.extend(row_lats)
        labels.extend(row_names)
        rates.extend(row_rates)

    data = dict(x=longitudes, y=latitudes, name=labels, rate=rates)
    columns = ['display_string', 'formatted']

    if use_cache:
        cache = dict()
        cache['data'] = data
        cache['city_data'] = filtered_array[columns]
        with open(cache_file_loc, 'wb') as handle:
            pickle.dump(cache, handle, protocol=pickle.HIGHEST_PROTOCOL)

    return data, filtered_array[columns]

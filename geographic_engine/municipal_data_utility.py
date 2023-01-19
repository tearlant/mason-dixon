from . import coordinate_utility


# This function is used both server-side (Web API calls in WGS) and client-side.
# Somewhat arbitrarily, it uses WGS coordinates, because this makes it easier to debug if there is an issue
def map_zoom_to_population(number_of_longitude_degrees):
    if number_of_longitude_degrees > 180:
        return 5e4, 5e6
    elif number_of_longitude_degrees > 120:
        return 3e4, 3e6
    elif number_of_longitude_degrees > 100:
        return 2.5e4, 2.5e6
    elif number_of_longitude_degrees > 80:
        return 2e4, 2e6
    elif number_of_longitude_degrees > 60:
        return 1.5e4, 1.5e6
    elif number_of_longitude_degrees > 50:
        return 1e4, 1e6
    elif number_of_longitude_degrees > 40:
        return 9e3, 9e5
    elif number_of_longitude_degrees > 30:
        return 8e3, 8e5
    elif number_of_longitude_degrees > 20:
        return 7e3, 7e5
    elif number_of_longitude_degrees > 15:
        return 6.5e3, 6.5e5
    elif number_of_longitude_degrees > 10:
        return 6e3, 6e5
    elif number_of_longitude_degrees > 7.5:
        return 5.5e3, 5.5e5
    elif number_of_longitude_degrees > 5:
        return 5e3, 5e5
    else:
        return 4e3, 4e5


# TODO: Consider case of wrapping around the international date line (Not sure if Bokeh tiles take care of it)
def map_wgs_window_to_population(upper_left, lower_right):
    longitude_degrees = abs(lower_right[0] - upper_left[0])
    return map_zoom_to_population(longitude_degrees)


def map_mercator_window_to_population(upper_left, lower_right):
    upper_left_wgs = coordinate_utility.point_to_wgs84(upper_left)
    lower_right_wgs = coordinate_utility.point_to_wgs84(lower_right)
    
    ul = (upper_left_wgs.x, upper_left_wgs.y)
    lr = (lower_right_wgs.x, lower_right_wgs.y)

    return map_wgs_window_to_population(ul, lr)


def get_cities_within_geometry(geometry, city_array, pop_threshold, additional_columns=()):
    cities_in_region = city_array[city_array['geometry'].within(geometry)]
    res = cities_in_region[cities_in_region['pop_max'] >= pop_threshold]
    columns = ['index', 'name', 'pop_max', 'geometry']
    columns.extend(additional_columns)
    return res[columns]


def rate_rule(multipolygon, city_array):
    cities_in_multipolygon = city_array[city_array['geometry'].within(multipolygon)]
    rates = cities_in_multipolygon['rate']
    if len(rates) == 0:
        return 0
    else:
        return rates.mean()

from pyproj import Transformer
from shapely.geometry import Polygon, MultiPolygon, Point

transformer = Transformer.from_crs(4326, 3857, always_xy=True)
transformer_inv = Transformer.from_crs(3857, 4326, always_xy=True)


def point_to_mercator(point):
    transformed = transformer.transform(point.x, point.y)
    return Point(*transformed)


def point_to_wgs84(point):
    transformed = transformer_inv.transform(point.x, point.y)
    return Point(*transformed)


def polygon_to_mercator(polygon):
    longitudes = polygon.exterior.coords.xy[0]
    latitudes = polygon.exterior.coords.xy[1]
    coords = zip(longitudes, latitudes)
    return Polygon([transformer.transform(c[0], c[1]) for c in coords])


def multipolygon_to_mercator(multipolygon):
    return MultiPolygon([polygon_to_mercator(polygon) for polygon in multipolygon.geoms])


def display_wgs_string(wgs_point):
    lon = wgs_point.x
    lat = wgs_point.y
    if lon >= 0:
        lon_string = ("%.2f" % lon) + u"\xb0E"
    else:
        lon_string = ("%.2f" % (-1 * lon)) + u"\xb0W"

    if lat >= 0:
        lat_string = ("%.2f" % lat) + u"\xb0N"
    else:
        lat_string = ("%.2f" % (-1 * lon)) + u" S"

    return f"({lat_string}, {lon_string})"

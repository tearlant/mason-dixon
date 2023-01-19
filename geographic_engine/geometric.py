from shapely.geometry import LineString, Polygon, MultiPolygon, Point


def _flat_map(xs):
    return [y for ys in xs for y in ys]


def wrap_polygon(geom):
    if geom.geom_type == 'GeometryCollection':
        res = []
        for x in geom.geoms:
            if x.geom_type == 'MultiPolygon' or x.geom_type == 'Polygon':
                res.append(x)

        return MultiPolygon(res)
    if geom.geom_type == 'MultiPolygon':
        return geom
    if geom.geom_type == 'Polygon':
        return MultiPolygon([geom])
    return MultiPolygon([])


def unroll_polygon(polygon, index):
    res = [list(polygon.exterior.coords.xy[index])]
    res.extend([list(ring.coords.xy[index]) for ring in polygon.interiors])
    return res


def unroll_multipolygon(multipolygon, index):
    res = [unroll_polygon(polygon, index) for polygon in multipolygon.geoms]
    return res


def split_multipolygon(multipolygon):
    mrr = multipolygon.minimum_rotated_rectangle
    mrr_points = list(zip(*mrr.exterior.coords.xy))
    m_pts = [object_to_point(pt) for pt in mrr_points]

    line1 = LineString((mrr_points[0], mrr_points[1]))
    line2 = LineString((mrr_points[1], mrr_points[2]))
    line3 = LineString((mrr_points[2], mrr_points[3]))
    line4 = LineString((mrr_points[3], mrr_points[0]))

    lines = [line1, line2, line3, line4]
    midpoints = [ls.centroid for ls in lines]

    length1 = LineString((midpoints[0], midpoints[2])).length
    length2 = LineString((midpoints[1], midpoints[3])).length

    # Quick and dirty fix needed after a package upgrade.
    # In the latest version of Shapely, this needs to be a list of tuples instead of Points
    m_pts = [(pt.x, pt.y) for pt in m_pts]
    midpoints = [(pt.x, pt.y) for pt in midpoints]

    if length1 > length2:
        rect1 = Polygon([m_pts[0], m_pts[1], midpoints[1], midpoints[3]])
        rect2 = Polygon([midpoints[1], m_pts[2], m_pts[3], midpoints[3]])
    else:
        rect1 = Polygon([m_pts[0], midpoints[0], midpoints[2], m_pts[3]])
        rect2 = Polygon([midpoints[0], m_pts[1], m_pts[2], midpoints[2]])

    res1 = multipolygon.intersection(rect1)
    res2 = multipolygon.intersection(rect2)

    return wrap_polygon(res1), wrap_polygon(res2)


# cut geometry into rectangular regions (recursively) until they are smaller than the maximal area allowed
def conditionally_split_multipolygon(multipolygon, largest_area, level=0):
    if multipolygon.area <= largest_area:
        return [multipolygon]

    r1, r2 = split_multipolygon(multipolygon)
    return _flat_map([conditionally_split_multipolygon(r1, largest_area, level + 1),
                     conditionally_split_multipolygon(r2, largest_area, level + 1)])


# repeat a string/value for every element of a multipolygon (For example, to force all components
# to have the same label/value)
def spread_over_multipolygon(name, multipolygon):
    return [name for _ in multipolygon.geoms]


def object_to_point(obj):
    if isinstance(obj, Point):
        return obj

    return Point(obj[0], obj[1])




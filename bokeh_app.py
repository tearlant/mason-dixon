import asyncio
import logging
import math
import reactivex
import pickle
import bokeh.palettes as bp
import colorcet as cc

from bokeh.events import RangesUpdate, Reset
from bokeh.plotting import figure
from bokeh.models import DataRange1d, LinearColorMapper, ColumnDataSource, MultiPolygons, TableColumn, DataTable
from shapely.geometry import Point
from tornado.websocket import websocket_connect
from bokeh.layouts import row, column

import mason_dixon.municipal_data_utility as mun_util
from mason_dixon import coordinate_utility
from mason_dixon.data_provider import DataProvider
from mason_dixon.map_data_creator import render_full_map
from client_side_utility import request_city_data_from_server


def bokeh_app(doc, cfg, data_provider: DataProvider):

    needs_update = True
    ready_for_rerender = reactivex.subject.Subject()

    ws_conn_url = "ws://localhost:8888/ws"
    ws_conn = None
    ws_conn_city_update_url = "ws://localhost:8888/get_cities"
    ws_conn_city_update = None

    # TODO: Clean this up (the values are overwritten on the initial server call anyway)
    upper_left_merc = (10000000, 24000000)
    lower_right_merc = (16000000, 29000000)

    box_factor = cfg["box_factor"]
    city_box_proportion = cfg["city_box_proportion"]

    city_array = data_provider.cities_dataframe_mercator.copy(deep=True)
    region_array = data_provider.region_dataframe.copy(deep=True)

    request_counter = 0
    last_response_received = 0
    server_session_guid = doc.session_context.request.arguments['guid'][0].decode('ascii')

    rerender_callback_id = None
    polling_callback_id = None

    # Due to asynchronicity, this flag is needed to clean some things up properly
    session_closed = False

    def check_if_needs_update(message):
        nonlocal needs_update, session_closed
        if session_closed:
            return

        deserialized = pickle.loads(message)
        logging.debug("MESSAGE RECEIVED --> " + str(deserialized))
        if ('session_open' in deserialized) and (not deserialized['session_open']):
            ws_conn.close()
            ws_conn_city_update.close()
            doc.remove_periodic_callback(polling_callback_id)
            doc.remove_periodic_callback(rerender_callback_id)
            session_closed = True
        elif 'needs_update' in deserialized:
            needs_update = deserialized['needs_update']

    def update_cities_table(message):
        def new_value(city):
            logging.debug("New municipal data received" + str(city))
            if city['update_counter'] <= city_array.loc[city['index'], 'updates']:
                # Update is stale. Return the current rate
                return city_array.loc[city['index'], 'rate']

            return city['rate']

        mapper = {d['index']: new_value(d) for d in message.city_list}
        city_array['rate'] = city_array['index'].map(mapper).fillna(city_array['rate'])

        mapper2 = {d['index']: max(d['update_counter'], city_array.loc[d['index'], 'updates']) for d in message.city_list}
        city_array['updates'] = city_array['index'].map(mapper2).fillna(city_array['updates'])

    def city_update_callback(message):
        nonlocal last_response_received
        if session_closed:
            return

        msg = pickle.loads(message)
        update_cities_table(msg)
        last_response_received = msg.request_id

    async def initialize():
        nonlocal ws_conn, ws_conn_city_update
        ws_conn = await websocket_connect(ws_conn_url, on_message_callback=check_if_needs_update)
        ws_conn_city_update = await websocket_connect(ws_conn_city_update_url, on_message_callback=city_update_callback)

    async def wait_for_counter(value):
        while last_response_received < value:
            await asyncio.sleep(0.01)

    def rerender():
        if session_closed:
            return

        logging.debug('rerender() - needs_update = ' + str(needs_update))
        if not needs_update:
            return

        # TODO: Check if the browser has closed and potentially destroy session
        logging.debug("rerender() - Rerender required")
        ready_for_rerender.on_next('Rerendering request sent')

    def poll_for_updates():
        if session_closed:
            return

        logging.debug('Polling for updates')
        payload = dict()
        payload['session_guid'] = server_session_guid
        ws_conn.write_message(pickle.dumps(payload), binary=True)

    async def produce_map(lon_wgs, lat_wgs, aspect_ratio, zoom, box_factor, city_box_proportion, palette):
        nonlocal request_counter, upper_left_merc, lower_right_merc
        frame_size = (zoom, zoom / aspect_ratio)
        upper_left_wgs = (lon_wgs, lat_wgs)
        lower_right_wgs = (upper_left_wgs[0] + frame_size[0], upper_left_wgs[1] - frame_size[1])

        upper_left_merc = coordinate_utility.point_to_mercator(Point(upper_left_wgs[0], upper_left_wgs[1]))
        lower_right_merc = coordinate_utility.point_to_mercator(Point(lower_right_wgs[0], lower_right_wgs[1]))

        # Difference from the prototype... full city_array needs to be passed here, instead of filtered.
        rect_data, table_data = render_full_map(upper_left_merc, lower_right_merc, box_factor, city_array, region_array, mun_util.rate_rule, city_box_proportion, True)

        # Maybe factor this into a helper function
        x_range = (upper_left_merc.x, lower_right_merc.x)
        y_range = (lower_right_merc.y, upper_left_merc.y)

        # 0.9 comes from trial and error.
        ar = abs((y_range[1] - y_range[0]) / (x_range[1] - x_range[0])) * 0.9
        x_range_dr = DataRange1d(start=x_range[0], end=x_range[1])
        y_range_dr = DataRange1d(start=y_range[0], end=y_range[1])

        rect_tools = "box_zoom,pan,wheel_zoom,reset,hover,save"
        initial_height = cfg["map_height"]

        p = figure(
            title="Aggregated units", tools=rect_tools, x_range=x_range_dr, y_range=y_range_dr,
            x_axis_type="mercator", y_axis_type="mercator",
            tooltips=[("Name", "@name"), ("Rate", "@rate{(0.0)}")],
            width=math.ceil(initial_height / ar), height=initial_height
        )

        p.grid.grid_line_color = None
        p.hover.point_policy = "follow_mouse"
        p.add_tile("CartoDB Positron", retina=True)
        # Bokeh's aspect ratio control makes this necessary. (It can be relaxed if we don't care about aspect ratio)
        p.match_aspect = True

        color_mapper = LinearColorMapper(palette=palette)

        source = ColumnDataSource(rect_data)
        ptch = MultiPolygons(xs="x", ys="y", line_width=0.5, fill_alpha=0.7, line_color="white",
                             fill_color=dict(field='rate', transform=color_mapper))
        p.add_glyph(source, ptch)
        #ptch = p.multi_polygons(xs="x", ys="y", source=rect_data, line_width=0.5, fill_alpha=0.7, line_color="white",
        #                     fill_color=dict(field='rate', transform=color_mapper))

        table_source = ColumnDataSource(table_data)

        columns = [
            TableColumn(field='display_string', title='City', width=200),
            TableColumn(field='formatted', title='Value', width=50),
        ]

        table = DataTable(source=table_source, columns=columns, index_position=None, height=initial_height, width=250)

        async def get_data_from_server_and_update(merc_upper_left, merc_lower_right):
            nonlocal request_counter
            wgs_upper_left = coordinate_utility.point_to_wgs84(merc_upper_left)
            wgs_lower_right = coordinate_utility.point_to_wgs84(merc_lower_right)
            new_zoom = abs(wgs_lower_right.x - wgs_upper_left.x)
            zoom_lat = abs(wgs_lower_right.y - wgs_upper_left.y)
            new_aspect_ratio = zoom / zoom_lat
            new_lon_wgs = wgs_upper_left.x
            new_lat_wgs = wgs_lower_right.y
            request_counter = request_counter + 1
            new_request_id = request_counter
            request_city_data_from_server(city_array, new_lon_wgs, new_lat_wgs, new_aspect_ratio, new_zoom, new_request_id, server_session_guid, ws_conn_city_update)
            await wait_for_counter(new_request_id)
            logging.debug("get_data_from_server_and_update: New data received")

            def apply_cb(rect_data, table_data):
                #ptch.data_source.data = data
                source.data = rect_data
                table_source.data = table_data
                logging.debug("get_data_from_server_and_update: New data applied")
            new_rect_data, new_table_data = render_full_map(merc_upper_left, merc_lower_right, box_factor, city_array, region_array, mun_util.rate_rule, city_box_proportion, False)
            # Some issues with locking, so put this in a next_tick_callback
            doc.add_next_tick_callback(lambda: apply_cb(new_rect_data, new_table_data))

        async def regenerate(string):
            logging.info(string)
            merc_upper_left = Point(p.x_range.start, p.y_range.start)
            merc_lower_right = Point(p.x_range.end, p.y_range.end)
            await get_data_from_server_and_update(merc_upper_left, merc_lower_right)

        # NOTE: This is in Mercator. Might need to keep coordinates straight.
        async def cb(event):
            merc_upper_left = Point(event.x0, event.y0)
            merc_lower_right = Point(event.x1, event.y1)
            await get_data_from_server_and_update(merc_upper_left, merc_lower_right)

        def client_side_callback(event):
            loop = asyncio.get_running_loop()
            loop.create_task(cb(event))

        def regeneration_callback(string):
            loop = asyncio.get_running_loop()
            loop.create_task(regenerate(string))

        p.on_event(RangesUpdate, client_side_callback)
        p.on_event(Reset, client_side_callback)
        ready_for_rerender.subscribe(regeneration_callback)

        return p, table

    async def create_initial_figure():
        nonlocal rerender_callback_id, polling_callback_id
        await initialize()

        lon = cfg["initial_lon_wgs"]
        lat = cfg["initial_lat_wgs"]
        aspect_ratio = cfg["aspect_ratio"]
        zoom = cfg["zoom"]

        # Good palettes are bp.Viridis11, cc.fire, cc.CET_L5, and cc.CET_L16
        palette = eval(f"{cfg['palette']}")

        p, table = await produce_map(lon, lat, aspect_ratio, zoom, box_factor, city_box_proportion, palette)
        r = row(p, table)
        #doc.add_next_tick_callback(lambda: doc.add_root(p))
        doc.add_next_tick_callback(lambda: doc.add_root(r))
        rerender_callback_id = doc.add_periodic_callback(rerender, 1000)
        polling_callback_id = doc.add_periodic_callback(poll_for_updates, 1000)

    loop = asyncio.get_running_loop()
    loop.create_task(create_initial_figure())

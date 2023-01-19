# coding=utf-8
import logging
import math
import os.path
import pickle
import uuid
import asyncio
import nest_asyncio
import numpy as np
from datetime import datetime

import tornado.httpserver
import tornado.ioloop
import tornado.websocket
import tornado.web
import tornado.options
from bokeh.client import pull_session

from bokeh.server.server import Server
from bokeh.embed import server_session

from geographic_engine.data_provider import DataProvider
from bokeh_app import bokeh_app
from geographic_engine.geodata_processing_utility import load_regions_into_json, load_cities_into_json
from map_creation import get_cached_indices_for_frame

tornado.options.define("port", default=8888, help="run on the given port", type=int)

create_data = False
data_prov = None
city_array = None
chunk_size = 40

# There are three caches
plotting_caches = dict()  # to be serialized and sent to bokeh server for synchronization
city_caches = dict()  # to optimize some of the API calls
local_caches = dict()  # to optimize some of the geospatial functions

# Static Functions


# This would be replaced with an API call if this is actually deployed. For now, it just pulls from the cache
async def rate_function(city):
    future = asyncio.Future()
    base_rate = city_array.loc[city['index'], 'rate']
    noise = np.random.uniform(-200, 700)
    future.set_result(base_rate + noise)
    return await future


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


def mark_session_for_updates(session_uid):
    logging.debug("Updating on the next cycle.")
    plotting_caches[session_uid]['update_counter'] += 1
    plotting_caches[session_uid]['needs_update'] = True


def mark_session_for_closure(session_uid):
    logging.info("Closing session for " + session_uid)
    plotting_caches[session_uid]['session_open'] = False


class CityUpdateMessage:
    def __init__(self, indices, city_cache, request_id, update_counter):
        cities = [city_cache[i] for i in indices]
        logging.debug('Request_id = ' + str(request_id) + ', Update_counter = ' + str(update_counter))
        city_info = [get_city_info(city) for city in cities]
        self.city_list = city_info
        self.request_id = request_id


# Tornado handlers
class BaseHandler(tornado.web.RequestHandler):
    def data_received(self, chunk):
        pass

    def get(self):
        uid = str(uuid.uuid4())
        self.set_cookie("session-uid", uid)
        plotting_caches[uid] = {
            'needs_update': False,
            'update_counter': 1,
            'session_open': True
        }
        city_caches[uid] = get_new_city_cache_wgs(city_array)

        # TODO: populate with a config file so that it is synchronized with Bokeh to start
        lon_wgs = -17.541988843581105
        lat_wgs = 64.48827612235075
        aspect_ratio = 1.514
        zoom = 40

        indices = get_cached_indices_for_frame(city_caches[uid], lon_wgs, lat_wgs, aspect_ratio, zoom)
        request_city_data_from_database(
            city_caches[uid], indices, rate_function, plotting_caches[uid]['update_counter'])

        local_caches[uid] = {
            'upper_left_lon': lon_wgs,
            'upper_left_lat': lat_wgs,
            'aspect_ratio': aspect_ratio,
            'zoom': zoom
        }
        logging.debug("GUID/Cookie = " + uid)

        ioloop = tornado.ioloop.IOLoop.current()

        args = {'guid': uid}
        with pull_session(url="http://localhost:5006/bokeh_app", io_loop=ioloop, arguments=args) as mysession:
            logging.debug("New Bokeh session id: " + mysession.id)
            plotting_caches[uid]['bokeh_session_id'] = mysession.id
            script = server_session(session_id=mysession.id, url="http://localhost:5006/bokeh_app")
            self.render("bootstrap_page.html", scr=script, username='', api_call_successful=False, api_call_data=None, distance=None, airport_code=None)


class ExitHandler(tornado.web.RequestHandler):
    def data_received(self, chunk):
        pass

    # When the user closes a tab, it closes the Tornado session but not the Bokeh session.
    # Set flag so that the Bokeh server sees the closure on the next poll for data
    def post(self):
        session_uid = self.get_cookie("session-uid")
        mark_session_for_closure(session_uid)


class ButtonHandler(tornado.web.RequestHandler):
    def data_received(self, chunk):
        pass

    def set_default_headers(self):
        self.set_header("Content-Type", 'application/json')

    def get(self):
        # TODO: Fail gracefully
        session_uid = self.get_cookie("session-uid")
        mark_session_for_updates(session_uid)

    def post(self):
        logging.debug("Updating on the next cycle.")
        session_uid = self.get_cookie("session-uid")
        mark_session_for_updates(session_uid)


class BokehWebSocketHandler(tornado.websocket.WebSocketHandler):
    def data_received(self, chunk):
        pass

    def open(self):
        logging.info("WebSocket opened")

    def on_message(self, message):
        decoded = pickle.loads(message)
        current_state = plotting_caches[decoded['session_guid']]
        self.write_message(pickle.dumps(current_state), binary=True)
        if current_state['needs_update']:
            logging.debug('Turning off updates')
        else:
            logging.debug('No update required')

        plotting_caches[decoded['session_guid']]['needs_update'] = False

    def on_close(self):
        logging.info("WebSocket closed")


class CityUpdateWebSocketHandler(tornado.websocket.WebSocketHandler):
    def data_received(self, chunk):
        pass

    def open(self):
        logging.info("WebSocket opened")

    def on_message(self, city_update_request):
        message_decoded = pickle.loads(city_update_request)
        number_of_chunks = math.ceil(len(message_decoded['indices']) / chunk_size)
        logging.debug("Number of chunks = " + str(number_of_chunks))
        indices = list(message_decoded['indices'])
        uid = message_decoded['session_guid']
        update_counter = plotting_caches[uid]['update_counter']

        city_cache = city_caches[uid]

        chunks = [range(i * chunk_size, min((i + 1) * chunk_size, len(indices))) for i in range(number_of_chunks)]

        async def retrieve(chunk):
            ran = [indices[x] for x in chunk]
            await request_city_data_from_database(city_cache, ran, rate_function, update_counter)
            retrieved_city_data = CityUpdateMessage(ran, city_cache, message_decoded['request_id'], plotting_caches[uid]['update_counter'])
            await self.write_message(pickle.dumps(retrieved_city_data), binary=True)

        async def pull_data_and_update_rates():
            tasks = [retrieve(chunk) for chunk in chunks]
            await asyncio.gather(*tasks)

        loop = asyncio.get_running_loop()
        loop.create_task(pull_data_and_update_rates())

    def on_close(self):
        logging.info("WebSocket closed")


class TornadoApplication(tornado.web.Application):
    def __init__(self):
        handlers = [
            (r"/", BaseHandler),
            (r"/exit", ExitHandler),
            (r"/click", ButtonHandler),
            (r"/ws", BokehWebSocketHandler),
            (r"/get_cities", CityUpdateWebSocketHandler)
        ]
        settings = dict(
                template_path=os.path.join(os.path.dirname(__file__), "templates"),
                static_path=os.path.join(os.path.dirname(__file__), "static"),
                #xsrf_cookies=True,
                #cookie_secret="YOUR SECRET HERE",
                debug=True
        )
        super().__init__(handlers, **settings)


if __name__ == '__main__':
    nest_asyncio.apply()
    log_filename = 'MasonDixon-' + datetime.utcnow().strftime('%Y%m%d%H%M%S') + '.log'
    log_filepath = os.path.join('logs', log_filename)
    logging.basicConfig(filename=log_filepath, encoding='utf-8', level=logging.INFO)
    #logging.basicConfig(encoding='utf-8', level=logging.DEBUG)

    if create_data:
        logging.info("Creating GeoJSON data")
        load_regions_into_json(False)
        load_cities_into_json(False)
        logging.info("Data loaded into GeoJSONs")

    logging.info("Loading data from GeoJSONs")
    data_prov = DataProvider(lambda coords: np.random.uniform(0, 2000))
    logging.info("Data fully loaded")

    # TODO: This should be replaced with an API call
    logging.info("Populating default price rates. While testing, only random numbers are being used")
    city_array = data_prov.get_cities_wgs()

    logging.info("Starting Tornado server.")
    http_server = tornado.httpserver.HTTPServer(TornadoApplication())
    logging.info("Listening on port: " + str(tornado.options.options.port))
    http_server.listen(tornado.options.options.port)
    io_loop = tornado.ioloop.IOLoop.current()

    bokeh_server = Server({'/bokeh_app': lambda doc: bokeh_app(doc, data_prov)},
                          io_loop=io_loop,
                          allow_websocket_origin=['localhost:8888'],
                          check_unused_sessions_milliseconds=1000,
                          unused_lifetime_milliseconds=1000
                          )

    print("App initialized.")

    io_loop.start()


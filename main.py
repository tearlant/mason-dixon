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
import yaml

import tornado.httpserver
import tornado.ioloop
import tornado.websocket
import tornado.web
import tornado.options

from bokeh.client import pull_session
from bokeh.server.server import Server
from bokeh.embed import server_session

from mason_dixon.data_provider import DataProvider
from mason_dixon.geodata_processing_utility import load_regions_into_json, load_cities_into_json
from bokeh_app import bokeh_app
from server_side_utility import get_cached_indices_for_frame, get_city_info, get_new_city_cache_wgs, request_city_data_from_database

tornado.options.define("port", default=8888, help="run on the given port", type=int)

data_prov = None
city_array = None

# There are three caches
plotting_caches = dict()  # to be serialized and sent to bokeh server for synchronization
city_caches = dict()  # to optimize some API calls
local_caches = dict()  # to optimize some geospatial functions

# Static Functions


# This would be replaced with an API call if this is actually deployed. Now, it just pulls from the cache and adds noise
# It returns a future (even though nothing is async about it) because it is a placeholder for a function or
# lambda expression containing an API call
async def rate_function(city):
    future = asyncio.Future()
    base_rate = city_array.loc[city['index'], 'rate']
    noise = np.random.uniform(-200, 700)
    future.set_result(base_rate + noise)
    return await future


def mark_session_for_updates(session_uid):
    logging.debug("Updating on the next cycle.")
    plotting_caches[session_uid]['update_counter'] += 1
    plotting_caches[session_uid]['needs_update'] = True


def mark_session_for_closure(session_uid):
    logging.info("Closing session for " + session_uid)
    plotting_caches[session_uid]['session_open'] = False


# Helper classes

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

        lon_wgs = cfg["initial_lon_wgs"]
        lat_wgs = cfg["initial_lat_wgs"]
        aspect_ratio = cfg["aspect_ratio"]
        zoom = cfg["zoom"]

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
        with pull_session(url=f"http://{cfg['bokeh_server_path']}/bokeh_app", io_loop=ioloop, arguments=args) as mysession:
            logging.debug("New Bokeh session id: " + mysession.id)
            plotting_caches[uid]['bokeh_session_id'] = mysession.id
            script = server_session(session_id=mysession.id, url=f"http://{cfg['bokeh_server_path']}/bokeh_app")
            self.render("bootstrap_page.html", scr=script, username='', api_call_successful=False, api_call_data=None, distance=None, airport_code=None)


class ExitHandler(tornado.web.RequestHandler):
    def data_received(self, chunk):
        pass

    def set_default_headers(self):
        self.set_header("Content-Type", 'application/json')
        self.set_header("Access-Control-Allow-Origin", self.request.headers["Origin"])
        self.set_header("Access-Control-Allow-Credentials", "true")
        self.set_header("Access-Control-Allow-Headers", "X-Requested-With, Content-Type, Authorization")
        self.set_header("Access-Control-Allow-Methods", "PUT,GET,POST,OPTIONS")

    # When the user closes the browser/tab, it triggers closure of the Tornado session but not the Bokeh session.
    # This can lead to a memory leak because there is an open websocket connection.
    # Set flag so that the Bokeh server sees the closure on the next poll for data, and can properly clean up.
    def post(self):
        session_uid = self.get_cookie("session-uid")
        mark_session_for_closure(session_uid)


class ButtonHandler(tornado.web.RequestHandler):
    def data_received(self, chunk):
        pass

    def set_default_headers(self):
        self.set_header("Content-Type", 'application/json')
        self.set_header("Access-Control-Allow-Origin", self.request.headers["Origin"])
        self.set_header("Access-Control-Allow-Credentials", "true")
        self.set_header("Access-Control-Allow-Headers", "X-Requested-With,_xsrf,Content-Type,Authorization")
        self.set_header("Access-Control-Allow-Methods", "PUT,GET,POST,OPTIONS")

    def get(self):
        # TODO: Fail gracefully
        session_uid = self.get_cookie("session-uid")
        mark_session_for_updates(session_uid)

    def post(self):
        logging.debug("Updating on the next cycle.")
        session_uid = self.get_cookie("session-uid")
        print(session_uid)
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

    with open("config.yml", "r") as ymlfile:
        cfg = yaml.safe_load(ymlfile)

    # Updates with a large number of cities are broken up into blocks
    chunk_size = cfg["chunk_size"]

    logging.info("Creating GeoJSON data")
    load_regions_into_json(False)
    load_cities_into_json(False)
    logging.info("Data loaded into GeoJSONs")

    logging.info("Loading data from GeoJSONs")
    # Starting with random values
    data_prov = DataProvider(lambda coords: np.random.uniform(500, 2000))
    logging.info("Data fully loaded")

    # TODO: This should be replaced with an API call
    logging.info("Populating starting values. While testing, only random numbers are being used.")
    city_array = data_prov.get_cities_wgs()

    logging.info("Starting Tornado server.")
    http_server = tornado.httpserver.HTTPServer(TornadoApplication())
    logging.info("Listening on port: " + str(tornado.options.options.port))
    http_server.listen(tornado.options.options.port)
    io_loop = tornado.ioloop.IOLoop.current()

    bokeh_server = Server({'/bokeh_app': lambda doc: bokeh_app(doc, cfg, data_prov)},
                          io_loop=io_loop,
                          allow_websocket_origin=cfg["websocket_origins"],
                          check_unused_sessions_milliseconds=1000,
                          unused_lifetime_milliseconds=1000
                          )

    print("App initialized.")

    io_loop.start()


#!/usr/bin/env python
"""
gw2copilot/server.py

The latest version of this package is available at:
<https://github.com/jantman/gw2copilot>

################################################################################
Copyright 2016 Jason Antman <jason@jasonantman.com> <http://www.jasonantman.com>

    This file is part of gw2copilot.

    gw2copilot is free software: you can redistribute it and/or modify
    it under the terms of the GNU Affero General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    gw2copilot is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU Affero General Public License for more details.

    You should have received a copy of the GNU Affero General Public License
    along with gw2copilot.  If not, see <http://www.gnu.org/licenses/>.

The Copyright and Authors attributions contained herein may not be removed or
otherwise altered, except to add the Author attribution of a contributor to
this work. (Additional Terms pursuant to Section 7b of the AGPL v3)
################################################################################
While not legally required, I sincerely request that anyone who finds
bugs please submit them at <https://github.com/jantman/gw2copilot> or
to me via email, and that you send any contributions or improvements
either as a pull request on GitHub, or to me via email.
################################################################################

AUTHORS:
Jason Antman <jason@jasonantman.com> <http://www.jasonantman.com>
################################################################################
"""

import logging
import platform
import os
import json
from datetime import datetime
from twisted.web.server import Site
from twisted.internet import reactor
from twisted.python import log
from autobahn.twisted.websocket import listenWS
from versionfinder import find_version

import gw2copilot.site
import gw2copilot.api
from .wine_mumble_reader import WineMumbleLinkReader
from .native_mumble_reader import NativeMumbleLinkReader
from .test_mumble_reader import TestMumbleLinkReader
from .playerinfo import PlayerInfo
from .caching_api_client import CachingAPIClient
from .websockets import BroadcastServerFactory, BroadcastServerProtocol

logger = logging.getLogger(__name__)
observer = log.PythonLoggingObserver(loggerName='twisted')
observer.start()

# suppress versionfinder logging
for lname in ['versionfinder', 'pip', 'git']:
    l = logging.getLogger(lname)
    l.setLevel(logging.CRITICAL)
    l.propagate = True


class TwistedServer(object):
    """
    TwistedServer is the heart of the application, which handles all IO and
    bridges the MumbleLink to the web frontend and other logic.
    """

    def __init__(self, poll_interval=5.0, bind_port=8080, test=None,
                 cache_dir=None, ws_port=8081, api_key=None):
        """
        Initialize the Twisted Server, the heart of the application...

        :param poll_interval: interval in seconds to poll MumbleLink
        :type poll_interval: float
        :param bind_port: port number to bind to / listen on
        :type bind_port: int
        :param test: if not None, use :py:class:`~.TestMumbleLinkReader` as
           our MumbleLink reader class, and pass this argument to its
           constructor.
        :type test: str
        :param cache_dir: absolute path to gw2copilot cache directory
        :type cache_dir: str
        :param ws_port: port for websocket server to listen on
        :type ws_port: int
        :param api_key: GW2 API Key
        :type api_key: str
        """
        self.ver_info = find_version('gw2copilot')
        logger.info('Installed version: %s', self.ver_info.long_str)
        self._poll_interval = poll_interval
        self._bind_port = bind_port
        self._api_key = api_key
        self._ws_port = ws_port
        self.reactor = reactor
        self._site = None
        self._api = None
        self._app = None
        self._ws_broadcast = None
        if cache_dir is None:
            cd = os.path.abspath(os.path.expanduser('~/.gw2copilot/cache'))
            logger.debug('Defaulting cache directory to: %s', cd)
            cache_dir = cd
        self._cache_dir = cache_dir
        self.cache = CachingAPIClient(cache_dir, api_key=api_key)
        self.cache.fill_persistent_cache()
        # saved state:
        self._mumble_link_data = None
        self._mumble_update_datetime = None
        self._mumble_reader = None
        self._test = test
        self.playerinfo = PlayerInfo(self.cache)
        self._pi_position = None
        self._pi_player_dict = None

    def update_mumble_data(self, mumble_data):
        """
        Process an update to the MumbleLink data. This should be called by
        MumbleLink readers to pass back data; they should NOT write directly
        to instance variables.

        :param mumble_data: Raw data received from GW2 via MumbleLink
        :type mumble_data: dict
        """
        logger.debug("Updating mumble data: %s", mumble_data)
        self._mumble_link_data = mumble_data
        self._mumble_update_datetime = datetime.now()
        self.playerinfo.update_mumble_link(mumble_data)
        if self.playerinfo.player_dict != self._pi_player_dict:
            logger.debug('player_dict changed')
            self._pi_player_dict = self.playerinfo.player_dict
            self._ws_send('player_dict', self._pi_player_dict)
        if self.playerinfo.position != self._pi_position:
            logger.debug('position changed')
            self._pi_position = self.playerinfo.position
            self._ws_send('position', self._pi_position)

    def _ws_send(self, msg_type, data):
        """
        Send the given data to all clients via websocket broadcast.

        :param msg_type: type of message; "tick", "position", "player_dict"
        :type msg_type: str
        :param data: JSON-serializable data dict
        :type data: dict
        """
        msg = json.dumps({'type': msg_type, 'data': data})
        self._ws_broadcast.broadcast(msg)

    @property
    def ws_port(self):
        """
        Return the websocket port number

        :return: websocket port number
        :rtype: int
        """
        return self._ws_port

    @property
    def mumble_update_datetime(self):
        """
        Return the datetime when mumble link data was last updated.

        :return: datetime when mumble link data was last updated
        :rtype: datetime.datetime
        """
        return self._mumble_update_datetime

    @property
    def raw_mumble_link_data(self):
        """
        Return the current raw mumble link data.

        :return: current raw MumbleLink data
        :rtype: dict
        """
        return self._mumble_link_data

    def _run_reactor(self):
        """Method to run the Twisted reactor; mock point for testing"""
        self.reactor.run()

    def _listentcp(self, site):
        """
        Setup TCP listener for the Site; helper method for testing

        :param site: Site to serve
        :type site: :py:class:`~.GW2CopilotSite`
        """
        logger.warning('Setting TCP listener on port %d for HTTP requests',
                       self._bind_port)
        self.reactor.listenTCP(self._bind_port, site)

    def _listenWS(self):
        """
        Setup websocket listener; helper method for testing.
        """
        logger.warning('Setting WebSocket listener on port %d', self._ws_port)
        port = listenWS(self._ws_broadcast)
        logger.debug("Websocket server listening on port %d", port.port)

    def _add_mumble_reader(self):
        """
        Figure out what platform we're on, and instantiate the right
        MumbleReader class for it.
        """
        if self._test:
            logger.warning('Using TestMumbleLinkReader - TEST DATA ONLY')
            self._mumble_reader = TestMumbleLinkReader(
                self, self._poll_interval, self._test)
        elif platform.system() == 'Linux':
            logger.debug("Using WineMumbleLinkReader on Linux platform")
            self._mumble_reader = WineMumbleLinkReader(
                self, self._poll_interval)
        elif platform.system() == 'Windows':
            logger.debug("Using NativeMumbleLinkReader on Windows platform")
            self._mumble_reader = NativeMumbleLinkReader(
                self, self._poll_interval)
        else:
            raise NotImplementedError("ERROR: don't know how to read"
                                      "MumbleLink on unsupported platform "
                                      "%s" % platform.system())

    def _setup_klein(self):
        """
        Setup Klein site classes

        This is broken out into a separate method so that doc generation
        (``docs/source/autoklein.py``) can setup the Klein site without
        running a reactor.
        """
        self._site = gw2copilot.site.GW2CopilotSite(self)
        self._app = self._site.app
        self._api = gw2copilot.api.GW2CopilotAPI(self._site.app, self)

    def _setup_websockets(self):
        """
        Setup the autobahn websocket server factory and protocol; set
        ``self._ws_broadcast``.
        """
        self._ws_broadcast = BroadcastServerFactory(
            u"ws://127.0.0.1:%s" % self._ws_port,
            self.reactor,
            enable_tick=False
        )
        self._ws_broadcast.protocol = BroadcastServerProtocol

    def run(self):
        """setup the web Site, start listening on port, setup the MumbleLink
        reader, and start the Twisted reactor"""
        # setup the web Site and HTTP listener
        self._setup_klein()
        self._setup_websockets()
        self._listentcp(Site(self._site.resource))
        self._listenWS()
        # setup the MumbleLink reader
        self._add_mumble_reader()
        # run the main reactor event loop
        logger.warning('Starting Twisted reactor (event loop)')
        self._run_reactor()

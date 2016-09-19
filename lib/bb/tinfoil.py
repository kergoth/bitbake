# tinfoil: a simple wrapper around cooker for bitbake-based command-line utilities
#
# Copyright (C) 2012 Intel Corporation
# Copyright (C) 2011 Mentor Graphics Corporation
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 as
# published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

import logging
import warnings
import os
import sys

import bb.cache
import bb.cooker
import bb.providers
import bb.utils
from bb.cooker import state, BBCooker, CookerFeatures
from bb.cookerdata import CookerConfiguration, ConfigParameters
import bb.fetch2

class Tinfoil:
    def __init__(self, output=sys.stdout, tracking=False, bblayers_only=False):
        # Needed to avoid deprecation warnings with python 2.6
        warnings.filterwarnings("ignore", category=DeprecationWarning)

        # Set up logging
        self.logger = logging.getLogger('BitBake')
        self._log_hdlr = logging.StreamHandler(output)
        bb.msg.addDefaultlogFilter(self._log_hdlr)
        format = bb.msg.BBLogFormatter("%(levelname)s: %(message)s")
        if output.isatty():
            format.enable_color()
        self._log_hdlr.setFormatter(format)
        self.logger.addHandler(self._log_hdlr)

        self.config = CookerConfiguration()
        configparams = TinfoilConfigParameters(parse_only=True)
        self.config.setConfigParameters(configparams)
        self.config.setServerRegIdleCallback(self.register_idle_function)
        features = []
        if tracking:
            features.append(CookerFeatures.BASEDATASTORE_TRACKING)
        self.bblayers_only = bblayers_only
        self.cooker = BBCooker(self.config, features, bblayers_only=bblayers_only)
        self.config_data = self.cooker.data
        if bblayers_only:
            self.cooker.handleCollections(self.config_data.getVar("BBFILE_COLLECTIONS", True))
        bb.providers.logger.setLevel(logging.ERROR)
        self.cooker_data = None

    def register_idle_function(self, function, data):
        pass

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        self.shutdown()

    def parseRecipes(self):
        sys.stderr.write("Parsing recipes..")
        self.logger.setLevel(logging.WARNING)

        try:
            while self.cooker.state in (state.initial, state.parsing):
                self.cooker.updateCache()
        except KeyboardInterrupt:
            self.cooker.shutdown()
            self.cooker.updateCache()
            sys.exit(2)

        self.logger.setLevel(logging.INFO)
        sys.stderr.write("done.\n")

        self.cooker_data = self.cooker.recipecaches['']

    def prepare(self, config_only = False):
        if not self.cooker_data:
            if config_only:
                if self.bblayers_only:
                    self.cooker.initConfigurationData()
                self.cooker.parseConfiguration()
                self.cooker_data = self.cooker.recipecaches['']
            else:
                self.parseRecipes()

        if self.bblayers_only:
            self.config_data = self.cooker.data
            self.bblayers_only = False

    def parse_recipe_file(self, fn, appends=True, appendlist=None, config_data=None):
        """
        Parse the specified recipe file (with or without bbappends)
        and return a datastore object representing the environment
        for the recipe.
        Parameters:
            fn: recipe file to parse - can be a file path or virtual
                specification
            appends: True to apply bbappends, False otherwise
            appendlist: optional list of bbappend files to apply, if you
                        want to filter them
            config_data: custom config datastore to use. NOTE: if you
                         specify config_data then you cannot use a virtual
                         specification for fn.
        """
        self.prepare()
        if appends and appendlist == []:
            appends = False
        if appends:
            if appendlist:
                appendfiles = appendlist
            else:
                if not hasattr(self.cooker, 'collection'):
                    raise Exception('You must call tinfoil.prepare() with config_only=False in order to get bbappends')
                appendfiles = self.cooker.collection.get_file_appends(fn)
        else:
            appendfiles = None
        if config_data:
            # We have to use a different function here if we're passing in a datastore
            localdata = bb.data.createCopy(config_data)
            envdata = bb.cache.parse_recipe(localdata, fn, appendfiles)['']
        else:
            # Use the standard path
            parser = bb.cache.NoCache(self.cooker.databuilder)
            envdata = parser.loadDataFull(fn, appendfiles)
        return envdata

    def shutdown(self):
        self.cooker.shutdown(force=True)
        self.cooker.post_serve()
        self.cooker.unlockBitbake()
        self.logger.removeHandler(self._log_hdlr)

class TinfoilConfigParameters(ConfigParameters):

    def __init__(self, **options):
        self.initial_options = options
        super(TinfoilConfigParameters, self).__init__()

    def parseCommandLine(self, argv=sys.argv):
        class DummyOptions:
            def __init__(self, initial_options):
                for key, val in initial_options.items():
                    setattr(self, key, val)

        return DummyOptions(self.initial_options), None

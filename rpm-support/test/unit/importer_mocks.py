# -*- coding: utf-8 -*-
#
# Copyright © 2011 Red Hat, Inc.
#
# This software is licensed to you under the GNU General Public
# License as published by the Free Software Foundation; either version
# 2 of the License (GPLv2) or (at your option) any later version.
# There is NO WARRANTY for this software, express or implied,
# including the implied warranties of MERCHANTABILITY,
# NON-INFRINGEMENT, or FITNESS FOR A PARTICULAR PURPOSE. You should
# have received a copy of GPLv2 along with this software; if not, see
# http://www.gnu.org/licenses/old-licenses/gpl-2.0.txt.
import os
import mock
from pulp.server.content.conduits.repo_sync import RepoSyncConduit
from pulp.server.content.conduits.unit_add import UnitAddConduit
from pulp.server.content.conduits.unit_import import ImportUnitConduit
from pulp.server.content.plugins.config import PluginCallConfiguration
from pulp.server.content.plugins.model import Unit

def get_sync_conduit(type_id=None, existing_units=None, pkg_dir=None):
    def side_effect(type_id, key, metadata, rel_path):
        if rel_path and pkg_dir:
            rel_path = os.path.join(pkg_dir, rel_path)
        unit = Unit(type_id, key, metadata, rel_path)
        return unit

    def get_units(criteria=None):
        ret_units = True
        if criteria and hasattr(criteria, "type_ids"):
            if type_id and type_id not in criteria.type_ids:
                ret_units = False
        if ret_units and existing_units:
            return existing_units
        return []

    sync_conduit = mock.Mock(spec=RepoSyncConduit)
    sync_conduit.init_unit.side_effect = side_effect
    sync_conduit.get_units = mock.Mock()
    sync_conduit.get_units.side_effect = get_units
    return sync_conduit

def get_import_conduit(source_units=None):
    def get_source_units(criteria=None):
        return source_units

    import_conduit = mock.Mock(spec=ImportUnitConduit)
    import_conduit.get_source_units.side_effect = get_source_units
    return import_conduit

def get_upload_conduit(type_id=None, unit_key=None, metadata=None, relative_path=None, pkg_dir=None):
    def side_effect(type_id, unit_key, metadata, relative_path):
        if relative_path and pkg_dir:
            relative_path = os.path.join(pkg_dir, relative_path)
        unit = Unit(type_id, unit_key, metadata, relative_path)
        return unit

    def get_units(criteria=None):
        ret_units = True
        if criteria and hasattr(criteria, "type_ids"):
            if type_id and type_id not in criteria.type_ids:
                ret_units = False
        return []

    upload_conduit = mock.Mock(spec=UnitAddConduit)
    upload_conduit.init_unit.side_effect = side_effect

    upload_conduit.get_units = mock.Mock()
    upload_conduit.get_units.side_effect = get_units

    upload_conduit.save_units = mock.Mock()
    upload_conduit.save_units.side_effect = side_effect

    upload_conduit.build_failure_report = mock.Mock()
    upload_conduit.build_failure_report.side_effect = side_effect

    upload_conduit.build_success_report = mock.Mock()
    upload_conduit.build_success_report.side_effect = side_effect

    return upload_conduit

def get_basic_config(*arg, **kwargs):
    plugin_config = {}
    repo_plugin_config = {}
    for key in kwargs:
        repo_plugin_config[key] = kwargs[key]
    config = PluginCallConfiguration(plugin_config, 
            repo_plugin_config=repo_plugin_config)
    return config
#!/usr/bin/python
#
# Copyright (c) 2011 Red Hat, Inc.
#
#
# This software is licensed to you under the GNU General Public
# License as published by the Free Software Foundation; either version
# 2 of the License (GPLv2) or (at your option) any later version.
# There is NO WARRANTY for this software, express or implied,
# including the implied warranties of MERCHANTABILITY,
# NON-INFRINGEMENT, or FITNESS FOR A PARTICULAR PURPOSE. You should
# have received a copy of GPLv2 along with this software; if not, see
# http://www.gnu.org/licenses/old-licenses/gpl-2.0.txt.

import datetime

import mock

import base
from pulp.common import dateutils, constants
from pulp.devel import mock_plugins
from pulp.plugins.model import PublishReport
from pulp.server.db.model.repository import Repo, RepoDistributor, RepoPublishResult
from pulp.server.exceptions import InvalidValue
import pulp.server.managers.repo.cud as repo_manager
import pulp.server.managers.repo.distributor as distributor_manager
import pulp.server.managers.repo.publish as publish_manager

# -- test cases ---------------------------------------------------------------

class RepoSyncManagerTests(base.PulpAsyncServerTests):

    def setUp(self):
        super(RepoSyncManagerTests, self).setUp()
        mock_plugins.install()

        # Create the manager instances for testing
        self.repo_manager = repo_manager.RepoManager()
        self.distributor_manager = distributor_manager.RepoDistributorManager()
        self.publish_manager = publish_manager.RepoPublishManager()

    def tearDown(self):
        super(RepoSyncManagerTests, self).tearDown()
        mock_plugins.reset()

    def clean(self):
        super(RepoSyncManagerTests, self).clean()
        Repo.get_collection().remove()
        RepoDistributor.get_collection().remove()
        RepoPublishResult.get_collection().remove()

    @mock.patch('pulp.server.managers.event.fire.EventFireManager.fire_repo_publish_started')
    @mock.patch('pulp.server.managers.event.fire.EventFireManager.fire_repo_publish_finished')
    def test_publish(self, mock_finished, mock_started):
        """
        Tests publish under normal conditions when everything is configured
        correctly.
        """

        # Setup
        publish_config = {'foo' : 'bar'}
        self.repo_manager.create_repo('repo-1')
        self.distributor_manager.add_distributor('repo-1', 'mock-distributor', publish_config, False, distributor_id='dist-1')
        self.distributor_manager.add_distributor('repo-1', 'mock-distributor-2', publish_config, False, distributor_id='dist-2')

        # Test
        self.publish_manager.publish('repo-1', 'dist-1', None)

        # Verify

        #   Database
        repo_distributor = RepoDistributor.get_collection().find_one({'repo_id' : 'repo-1', 'id' : 'dist-1'})
        self.assertTrue(repo_distributor['last_publish'] is not None)
        self.assertTrue(assert_last_sync_time(repo_distributor['last_publish']))

        #   History
        entries = list(RepoPublishResult.get_collection().find({'repo_id' : 'repo-1'}))
        self.assertEqual(1, len(entries))
        self.assertEqual('repo-1', entries[0]['repo_id'])
        self.assertEqual('dist-1', entries[0]['distributor_id'])
        self.assertEqual('mock-distributor', entries[0]['distributor_type_id'])
        self.assertTrue(entries[0]['started'] is not None)
        self.assertTrue(entries[0]['completed'] is not None)
        self.assertEqual(RepoPublishResult.RESULT_SUCCESS, entries[0]['result'])
        self.assertTrue(entries[0]['summary'] is not None)
        self.assertTrue(entries[0]['details'] is not None)
        self.assertTrue(entries[0]['error_message'] is None)
        self.assertTrue(entries[0]['exception'] is None)
        self.assertTrue(entries[0]['traceback'] is None)

        #   Call into the correct distributor
        call_args = mock_plugins.MOCK_DISTRIBUTOR.publish_repo.call_args[0]

        self.assertEqual('repo-1', call_args[0].id)
        self.assertTrue(call_args[1] is not None)
        self.assertEqual({}, call_args[2].plugin_config)
        self.assertEqual(publish_config, call_args[2].repo_plugin_config)
        self.assertEqual({}, call_args[2].override_config)

        self.assertEqual(0, mock_plugins.MOCK_DISTRIBUTOR_2.publish_repo.call_count)

        self.assertEqual(1, mock_started.call_count)
        self.assertEqual('repo-1', mock_started.call_args[0][0])

        self.assertEqual(1, mock_finished.call_count)
        self.assertEqual('repo-1', mock_finished.call_args[0][0]['repo_id'])

    def test_publish_failure_report(self):
        """
        Tests a publish call that indicates a graceful failure.
        """
        # Setup
        publish_config = {'foo' : 'bar'}
        self.repo_manager.create_repo('repo-1')
        self.distributor_manager.add_distributor('repo-1', 'mock-distributor', publish_config, False, distributor_id='dist-1')

        mock_plugins.MOCK_DISTRIBUTOR.publish_repo.return_value = PublishReport(False, 'Summary of the publish', 'Details of the publish')

        # Test
        self.publish_manager.publish('repo-1', 'dist-1', None)

        # Verify
        entries = list(RepoPublishResult.get_collection().find({'repo_id' : 'repo-1'}))
        self.assertEqual(1, len(entries))
        self.assertEqual('repo-1', entries[0]['repo_id'])
        self.assertEqual('dist-1', entries[0]['distributor_id'])
        self.assertEqual('mock-distributor', entries[0]['distributor_type_id'])
        self.assertTrue(entries[0]['started'] is not None)
        self.assertTrue(entries[0]['completed'] is not None)
        self.assertEqual(RepoPublishResult.RESULT_FAILED, entries[0]['result'])
        self.assertTrue(entries[0]['summary'] is not None)
        self.assertTrue(entries[0]['details'] is not None)
        self.assertTrue(entries[0]['error_message'] is None)
        self.assertTrue(entries[0]['exception'] is None)
        self.assertTrue(entries[0]['traceback'] is None)

        # Cleanup
        mock_plugins.reset()

    def test_publish_with_config_override(self):
        """
        Tests a publish when passing in override values.
        """

        # Setup
        distributor_config = {'key-1' : 'orig-1', 'key-2' : 'orig-2'}
        self.repo_manager.create_repo('repo-1')
        self.distributor_manager.add_distributor('repo-1', 'mock-distributor', distributor_config, False, 'dist-2')

        # Test
        publish_overrides = {'key-1' : 'new-1', 'key-3' : 'new-3'}
        self.publish_manager.publish('repo-1', 'dist-2', publish_overrides)

        # Verify call into mock
        call_args = mock_plugins.MOCK_DISTRIBUTOR.publish_repo.call_args[0]

        self.assertEqual('repo-1', call_args[0].id)
        self.assertTrue(call_args[1] is not None)
        self.assertEqual({}, call_args[2].plugin_config)
        self.assertEqual(distributor_config, call_args[2].repo_plugin_config)
        self.assertEqual(publish_overrides, call_args[2].override_config)

    def test_publish_missing_repo(self):
        """
        Tests the proper error is raised when a non-existent repo is specified.
        """

        # Test
        try:
            self.publish_manager.publish('not-here', 'doesnt-matter', None)
            self.fail('Expected exception was not raised')
        except publish_manager.MissingResource, e:
            self.assertTrue('not-here' == e.resources['resource_id'])
            print(e) # for coverage

    def test_publish_no_distributor(self):
        """
        Tests the proper error is raised when a non-existed distributor is specified.
        """

        # Setup
        self.repo_manager.create_repo('no-dist')

        # Test
        try:
            self.publish_manager.publish('no-dist', 'fake-dist')
            self.fail('Expected exception was not raised')
        except publish_manager.MissingResource, e:
            self.assertTrue('no-dist' == e.resources['repository'])
            print(e) # for coverage

    def test_publish_bad_distributor(self):
        """
        Tests the proper error is raised when a distributor is set but the distributor
        is no longer present as a plugin.
        """

        # Setup
        self.repo_manager.create_repo('repo')
        self.distributor_manager.add_distributor('repo', 'mock-distributor', {}, False, distributor_id='dist-1')

        #   Simulate bouncing the server and removing the distributor plugin
        mock_plugins.DISTRIBUTOR_MAPPINGS.pop('mock-distributor')

        # Test
        try:
            self.publish_manager.publish('repo', 'dist-1', None)
            self.fail('Expected exception was not raised')
        except publish_manager.MissingResource, e:
            self.assertTrue('repo' == e.resources['resource_id'])
            print(e) # for coverage

    def test_publish_bad_database(self):
        """
        Tests the case where the database is in a bad state and no longer has the
        repo-distributor relationship collection.
        """

        # Setup
        self.repo_manager.create_repo('repo')
        self.distributor_manager.add_distributor('repo', 'mock-distributor', {}, False, distributor_id='dist-1')

        RepoDistributor.get_collection().remove()

        # Test
        try:
            self.publish_manager.publish('repo', 'dist-1')
            self.fail('Expected exception was not raised')
        except publish_manager.MissingResource, e:
            self.assertTrue('repo' == e.resources['repository'])
            print(e) # for coverage

    def test_publish_with_error(self):
        """
        Tests a publish when the plugin raises an error.
        """

        # Setup
        mock_plugins.MOCK_DISTRIBUTOR.publish_repo.side_effect = Exception()

        self.repo_manager.create_repo('gonna-bail')
        self.distributor_manager.add_distributor('gonna-bail', 'mock-distributor', {}, False, distributor_id='bad-dist')

        # Test
        try:
            self.publish_manager.publish('gonna-bail', 'bad-dist')
            self.fail('Expected exception was not raised')
        except publish_manager.PulpExecutionException, e:
            print(e) # for coverage

        # Verify
        repo_distributor = RepoDistributor.get_collection().find_one({'repo_id' : 'gonna-bail', 'id' : 'bad-dist'})

        self.assertTrue(repo_distributor is not None)
        self.assertTrue(assert_last_sync_time(repo_distributor['last_publish']))

        entries = list(RepoPublishResult.get_collection().find({'repo_id' : 'gonna-bail'}))
        self.assertEqual(1, len(entries))
        self.assertEqual('gonna-bail', entries[0]['repo_id'])
        self.assertEqual('bad-dist', entries[0]['distributor_id'])
        self.assertEqual('mock-distributor', entries[0]['distributor_type_id'])
        self.assertTrue(entries[0]['started'] is not None)
        self.assertTrue(entries[0]['completed'] is not None)
        self.assertEqual(RepoPublishResult.RESULT_ERROR, entries[0]['result'])
        self.assertTrue(entries[0]['summary'] is None)
        self.assertTrue(entries[0]['details'] is None)
        self.assertTrue(entries[0]['error_message'] is not None)
        self.assertTrue(entries[0]['exception'] is not None)
        self.assertTrue(entries[0]['traceback'] is not None)

        # Cleanup
        mock_plugins.MOCK_DISTRIBUTOR.publish_repo.side_effect = None

    def _test_auto_publish_for_repo(self):
        """
        Tests automatically publishing for a repo that has both auto and non-auto
        distributors configured.
        """

        # Setup
        self.repo_manager.create_repo('publish-me')
        self.distributor_manager.add_distributor('publish-me', 'mock-distributor', {}, True, 'auto')
        self.distributor_manager.add_distributor('publish-me', 'mock-distributor-2', {}, False, 'manual')

        # Test
        self.publish_manager.auto_publish_for_repo('publish-me')

        # Verify
        self.assertEqual(1, mock_plugins.MOCK_DISTRIBUTOR.publish_repo.call_count)
        self.assertEqual(0, mock_plugins.MOCK_DISTRIBUTOR_2.publish_repo.call_count)

    def test_auto_publish_no_repo(self):
        """
        Tests that calling auto publish on a repo that doesn't exist or one that
        doesn't have any distributors assigned will not error.
        """

        # Test
        self.publish_manager.auto_publish_for_repo('non-existent') # should not error

    def test_auto_publish_with_error(self):
        """
        Tests that if one auto distributor raises an error the other is still
        invoked and the error properly conveys the results.
        """

        # Setup
        mock_plugins.MOCK_DISTRIBUTOR.publish_repo.side_effect = Exception()

        self.repo_manager.create_repo('publish-me')
        self.distributor_manager.add_distributor('publish-me', 'mock-distributor', {}, True, 'auto-1')
        self.distributor_manager.add_distributor('publish-me', 'mock-distributor-2', {}, True, 'auto-2')

        # Test
        try:
            self.publish_manager.auto_publish_for_repo('publish-me')
            self.fail('Expected exception was not raised')
        except publish_manager.PulpExecutionException, e:
            pass
            # FIXME needs custom exception
            #self.assertTrue('publish-me' in e)
            # Commenting these out for now until exception object is flushed out
            #self.assertEqual(1, len(e.dist_traceback_tuples))
            #self.assertEqual('auto-1', e.dist_traceback_tuples[0][0])
            #self.assertTrue(e.dist_traceback_tuples[0][1] is not None)
            #print(e) # for coverage
            #print(e.dist_traceback_tuples[0][1]) # for curiosity of the exception format

        # Cleanup
        mock_plugins.MOCK_DISTRIBUTOR.publish_repo.side_effect = None

    def test_last_publish(self):
        """
        Tests retrieving the last publish instance.
        """

        # Setup
        expected = datetime.datetime(year=2020, month=4, day=12, hour=0, minute=23)
        date_str = dateutils.format_iso8601_datetime(expected)

        dist = RepoDistributor('repo-1', 'dist-1', 'type-1', None, True)
        dist['last_publish'] = date_str
        RepoDistributor.get_collection().save(dist)

        # Test
        last = self.publish_manager.last_publish('repo-1', 'dist-1')

        # Verify
        self.assertEqual(expected, last)

    def test_last_publish_never_published(self):
        """
        Tests getting the last publish date for an unpublished repo.
        """

        # Setup
        dist = RepoDistributor('repo-1', 'dist-1', 'type-1', None, True)
        RepoDistributor.get_collection().save(dist)

        # Test
        last = self.publish_manager.last_publish('repo-1', 'dist-1') # should not error

        # Verify
        self.assertTrue(last is None)

    def test_publish_no_plugin_report(self):
        """
        Tests publishing against a sloppy plugin that doesn't return a report.
        """

        # Setup
        self.repo_manager.create_repo('sloppy')
        self.distributor_manager.add_distributor('sloppy', 'mock-distributor', {}, True, distributor_id='slop')

        mock_plugins.MOCK_DISTRIBUTOR.publish_repo.return_value = None # lame plugin

        # Test
        self.publish_manager.publish('sloppy', 'slop')

        # Verify
        entries = list(RepoPublishResult.get_collection().find({'repo_id' : 'sloppy'}))
        self.assertEqual(1, len(entries))
        self.assertEqual('Unknown', entries[0]['summary'])
        self.assertEqual('Unknown', entries[0]['details'])

    def test_publish_history(self):
        """
        Tests getting the history of publishes on a repo.
        """

        # Setup
        self.repo_manager.create_repo('foo')
        self.distributor_manager.add_distributor('foo', 'mock-distributor', {}, True, distributor_id='dist-1')
        for i in range(1, 6):
            add_result('foo', 'dist-1', i)

        # Test
        entries = self.publish_manager.publish_history('foo', 'dist-1')

        # Verify. The returned entries should be limited to the constant defined in common.constants.
        self.assertEqual(constants.REPO_HISTORY_LIMIT, len(entries))

        #   Verify the default sort direction is descending order
        for i in range(0, 4):
            first = dateutils.parse_iso8601_datetime(entries[i]['started'])
            second = dateutils.parse_iso8601_datetime(entries[i + 1]['started'])
            self.assertTrue(first >= second)

    def test_publish_history_with_limit(self):
        """
        Tests using the limit to retrieve only a subset of the history.
        """

        # Setup
        self.repo_manager.create_repo('dragon')
        self.distributor_manager.add_distributor('dragon', 'mock-distributor', {}, True, distributor_id='fire')
        for i in range(0, 10):
            add_result('dragon', 'fire', i)

        # Test a valid limit
        entries = self.publish_manager.publish_history('dragon', 'fire', limit=3)
        self.assertEqual(3, len(entries))

    def test_publish_history_invalid_limit(self):
        """
        Tests that limit is checked for invalid values
        """

        # Setup
        self.repo_manager.create_repo('test_repo')
        self.distributor_manager.add_distributor('test_repo', 'mock-distributor', {}, True,
                                                 distributor_id='dist')

        # Verify an invalid limit raises an InvalidValue exception
        self.assertRaises(InvalidValue, self.publish_manager.publish_history, 'test_repo', 'dist',
                          limit=0)
        # Verify a non-int still raises an InvalidValue exception
        self.assertRaises(InvalidValue, self.publish_manager.publish_history, 'test_repo', 'dist',
                          limit='bacon')

    def test_publish_history_ascending_sort(self):
        """
        Tests use the sort parameter to sort the results in ascending order by start time
        """

        # Setup
        self.repo_manager.create_repo('test_sort')
        self.distributor_manager.add_distributor('test_sort', 'mock-distributor', {}, True,
                                                 distributor_id='test_dist')
        # Create some consecutive publish entries
        date_string = '2013-06-01T12:00:0%sZ'
        for i in range(0, 10, 2):
            r = RepoPublishResult.expected_result('test_sort', 'test_dist', 'bar', date_string % str(i),
                                                  date_string % str(i + 1), 'test-summary',
                                                  'test-details', RepoPublishResult.RESULT_SUCCESS)
            RepoPublishResult.get_collection().insert(r, safe=True)

        # Test that returned entries are in ascending order by time
        entries = self.publish_manager.publish_history('test_sort', 'test_dist',
                                                       sort=constants.SORT_ASCENDING)
        self.assertEqual(5, len(entries))
        for i in range(0, 4):
            first = dateutils.parse_iso8601_datetime(entries[i]['started'])
            second = dateutils.parse_iso8601_datetime(entries[i + 1]['started'])
            self.assertTrue(first < second)

    def test_publish_history_descending_sort(self):
        """
        Tests use the sort parameter to sort the results in descending order by start time
        """

        # Setup
        self.repo_manager.create_repo('test_sort')
        self.distributor_manager.add_distributor('test_sort', 'mock-distributor', {}, True,
                                                 distributor_id='test_dist')
        # Create some consecutive publish entries
        date_string = '2013-06-01T12:00:0%sZ'
        for i in range(0, 10, 2):
            r = RepoPublishResult.expected_result('test_sort', 'test_dist', 'bar', date_string % str(i),
                                                  date_string % str(i + 1), 'test-summary',
                                                  'test-details',RepoPublishResult.RESULT_SUCCESS)
            RepoPublishResult.get_collection().insert(r, safe=True)

        # Test that returned entries are in descending order by time
        entries = self.publish_manager.publish_history('test_sort', 'test_dist',
                                                       sort=constants.SORT_DESCENDING)
        self.assertEqual(5, len(entries))
        for i in range(0, 4):
            first = dateutils.parse_iso8601_datetime(entries[i]['started'])
            second = dateutils.parse_iso8601_datetime(entries[i + 1]['started'])
            self.assertTrue(first > second)

    def test_publish_history_invalid_sort(self):
        """
        Tests that publish_history checks the sort parameter for invalid values
        """

         # Setup
        self.repo_manager.create_repo('test_sort')
        self.distributor_manager.add_distributor('test_sort', 'mock-distributor', {}, True,
                                                 distributor_id='test_dist')

        # Test that an exception is raised if sort gets an invalid value
        self.assertRaises(InvalidValue, self.publish_manager.publish_history, 'test_sort', 'test_dist',
                          sort='random')

    def test_publish_history_start_date(self):

        # Setup
        self.repo_manager.create_repo('test_date')
        self.distributor_manager.add_distributor('test_date', 'mock-distributor', {}, True,
                                                 distributor_id='test_dist')
        # Create three consecutive publish entries
        date_string = '2013-06-01T12:00:0%sZ'
        for i in range(0, 6, 2):
            r = RepoPublishResult.expected_result('test_date', 'test_dist', 'bar', date_string % str(i),
                                                  date_string % str(i + 1), 'test-summary',
                                                  'test-details', RepoPublishResult.RESULT_SUCCESS)
            RepoPublishResult.get_collection().insert(r, safe=True)

        # Verify
        self.assertEqual(3, len(self.publish_manager.publish_history('test_date', 'test_dist')))
        start_date = '2013-06-01T12:00:02Z'
        start_entries = self.publish_manager.publish_history('test_date', 'test_dist',
                                                             start_date=start_date)
        # Confirm the dates of the retrieved entries are later than or equal to the requested date
        self.assertEqual(2, len(start_entries))
        for entries in start_entries:
            retrieved = dateutils.parse_iso8601_datetime(entries['started'])
            given_start = dateutils.parse_iso8601_datetime(start_date)
            self.assertTrue(retrieved >= given_start)

    def test_publish_history_end_date(self):

        # Setup
        self.repo_manager.create_repo('test_date')
        self.distributor_manager.add_distributor('test_date', 'mock-distributor', {}, True,
                                                 distributor_id='test_dist')
        # Create three consecutive publish entries
        date_string = '2013-06-01T12:00:0%sZ'
        for i in range(0, 6, 2):
            r = RepoPublishResult.expected_result('test_date', 'test_dist', 'bar', date_string % str(i),
                                                  date_string % str(i + 1), 'test-summary',
                                                  'test-details', RepoPublishResult.RESULT_SUCCESS)
            RepoPublishResult.get_collection().insert(r, safe=True)

        # Verify that all entries retrieved have dates prior to the given end date
        end_date = '2013-06-01T12:00:03Z'
        end_entries = self.publish_manager.publish_history('test_date', 'test_dist', end_date=end_date)
        # Confirm the dates of the retrieved entries are earlier than or equal to the requested date
        self.assertEqual(2, len(end_entries))
        for entries in end_entries:
            retrieved = dateutils.parse_iso8601_datetime(entries['started'])
            given_end = dateutils.parse_iso8601_datetime(end_date)
            self.assertTrue(retrieved <= given_end)

    def test_publish_history_invalid_date(self):

        # Setup
        self.repo_manager.create_repo('test_date')
        self.distributor_manager.add_distributor('test_date', 'mock-distributor', {}, True,
                                                 distributor_id='test_dist')
        for i in range(1, 5):
            add_result('test_date', 'test_dist', i)

        # Verify exceptions are raised when malformed dates are given
        self.assertRaises(InvalidValue, self.publish_manager.publish_history, 'test_date', 'test_dist',
                          start_date='2013-56-01T12:00:02Z')
        self.assertRaises(InvalidValue, self.publish_manager.publish_history, 'test_date', 'test_dist',
                          end_date='2013-56-01T12:00:02Z')

    def test_publish_history_missing_repo(self):
        """
        Tests the correct error is raised when getting history for a repo that doesn't exist.
        """

        # Test
        self.assertRaises(publish_manager.MissingResource, self.publish_manager.publish_history, 'missing', 'irrelevant')

    # -- utility tests --------------------------------------------------------

    def _test_auto_distributors(self):
        """
        Tests that the query for distributors on a repo that are configured for automatic distribution is correct.
        """

        # Setup
        dist_coll = RepoDistributor.get_collection()

        dist_coll.save(RepoDistributor('repo-1', 'dist-1', 'type', {}, True))
        dist_coll.save(RepoDistributor('repo-1', 'dist-2', 'type', {}, True))
        dist_coll.save(RepoDistributor('repo-1', 'dist-3', 'type', {}, False))
        dist_coll.save(RepoDistributor('repo-2', 'dist-1', 'type', {}, True))
        dist_coll.save(RepoDistributor('repo-2', 'dist-2', 'type', {}, False))

        # Test
        repo1_dists = publish_manager._auto_distributors('repo-1')
        repo2_dists = publish_manager._auto_distributors('repo-2')
        repo3_dists = publish_manager._auto_distributors('repo-3')

        # Verify
        self.assertEqual(2, len(repo1_dists))
        repo1_dist_ids = [d['id'] for d in repo1_dists]
        self.assertTrue('dist-1' in repo1_dist_ids)
        self.assertTrue('dist-2' in repo1_dist_ids)

        self.assertEqual(1, len(repo2_dists))
        repo2_dist_ids = [d['id'] for d in repo2_dists]
        self.assertTrue('dist-1' in repo2_dist_ids)

        self.assertEqual(0, len(repo3_dists))

# -- testing utilities --------------------------------------------------------

def assert_last_sync_time(time_in_iso):
    now = datetime.datetime.now(dateutils.local_tz())
    finished = dateutils.parse_iso8601_datetime(time_in_iso)

    # Compare them within a threshold since they won't be exact
    difference = now - finished
    return difference.seconds < 2

def add_result(repo_id, dist_id, offset):
    started = datetime.datetime.now(dateutils.local_tz())
    completed = started + datetime.timedelta(days=offset)
    r = RepoPublishResult.expected_result(repo_id, dist_id, 'bar', dateutils.format_iso8601_datetime(started), dateutils.format_iso8601_datetime(completed), 'test-summary', 'test-details', RepoPublishResult.RESULT_SUCCESS)
    RepoPublishResult.get_collection().insert(r, safe=True)

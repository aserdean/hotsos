import json
import mock
import os
import shutil
import tempfile
import utils

from core import checks
from core import constants
from core.ycheck.bugs import YBugChecker
from core.ycheck.configs import YConfigChecker
from core.ycheck.scenarios import YScenarioChecker
from core.issues import issue_types
from core.plugins.storage import (
    ceph as ceph_core,
)
from plugins.storage.pyparts import (
    bcache,
    ceph_cluster_checks,
    ceph_event_checks,
    ceph_service_info,
)

CEPH_CONF_NO_BLUESTORE = """
[global]
[osd]
osd objectstore = filestore
osd journal size = 1024
filestore xattr use omap = true
"""

CEPH_VERSIONS_MISMATCHED_MAJOR = """
{
    "mon": {
        "ceph version 15.2.13 (c44bc49e7a57a87d84dfff2a077a2058aa2172e2) octopus (stable)": 1
    },
    "mgr": {
        "ceph version 15.2.13 (c44bc49e7a57a87d84dfff2a077a2058aa2172e2) octopus (stable)": 1
    },
    "osd": {
        "ceph version 15.2.13 (c44bc49e7a57a87d84dfff2a077a2058aa2172e2) octopus (stable)": 2,
        "ceph version 14.2.18 (b77bc49e3a57a87d84df112a087a2058aa217118) nautilus (stable)": 1
    },
    "mds": {},
    "overall": {
        "ceph version 15.2.13 (c44bc49e7a57a87d84dfff2a077a2058aa2172e2) octopus (stable)": 5
    }
}
"""  # noqa


CEPH_VERSIONS_MISMATCHED_MINOR = """
{
    "mon": {
        "ceph version 15.2.11 (e3523634d9c2227df9af89a4eac33d16738c49cb) octopus (stable)": 3
    },
    "mgr": {
        "ceph version 15.2.11 (e3523634d9c2227df9af89a4eac33d16738c49cb) octopus (stable)": 3
    },
    "osd": {
        "ceph version 15.2.11 (e3523634d9c2227df9af89a4eac33d16738c49cb) octopus (stable)": 208,
        "ceph version 15.2.13 (c44bc49e7a57a87d84dfff2a077a2058aa2172e2) octopus (stable)": 16
    },
    "mds": {},
    "overall": {
        "ceph version 15.2.11 (e3523634d9c2227df9af89a4eac33d16738c49cb) octopus (stable)": 217,
        "ceph version 15.2.13 (c44bc49e7a57a87d84dfff2a077a2058aa2172e2) octopus (stable)": 16
    }
}
"""  # noqa

CEPH_OSD_CRUSH_DUMP = """
{
        "buckets": [
            {
                "id": -1,
                "name": "default",
                "type_id": 11,
                "type_name": "root",
                "weight": 1926,
                "alg": "straw2",
                "hash": "rjenkins1",
                "items": [
                    {
                        "id": -3,
                        "weight": 642,
                        "pos": 0
                    },
                    {
                        "id": -5,
                        "weight": 642,
                        "pos": 1
                    },
                    {
                        "id": -7,
                        "weight": 642,
                        "pos": 2
                    }
                ]
            },
            {
                "id": -3,
                "name": "juju-94442c-oct00-1",
                "type_id": 1,
                "type_name": "host",
                "weight": 642,
                "alg": "straw2",
                "hash": "rjenkins1",
                "items": [
                    {
                        "id": 1,
                        "weight": 642,
                        "pos": 0
                    }
                ]
            },
            {
                "id": -5,
                "name": "juju-94442c-oct00-3",
                "type_id": 1,
                "type_name": "host",
                "weight": 642,
                "alg": "straw2",
                "hash": "rjenkins1",
                "items": [
                    {
                        "id": 0,
                        "weight": 642,
                        "pos": 0
                    }
                ]
            },
            {
                "id": -7,
                "name": "juju-94442c-oct00-2",
                "type_id": 3,
                "type_name": "rack00",
                "weight": 642,
                "alg": "straw2",
                "hash": "rjenkins1",
                "items": [
                    {
                        "id": 2,
                        "weight": 642,
                        "pos": 0
                    }
                ]
            }
        ]
    }
"""

PG_DUMP_JSON_DECODED = {'pg_map': {
                          'pg_stats': [
                            {'stat_sum': {'num_large_omap_objects': 1},
                             'last_scrub_stamp': '2021-09-16T21:26:00.00',
                             'last_deep_scrub_stamp': '2021-09-16T21:26:00.00',
                             'pgid': '2.f',
                             'state': 'active+clean+laggy'}]}}


class StorageTestsBase(utils.BaseTestCase):

    def setUp(self):
        super().setUp()
        os.environ['PLUGIN_NAME'] = 'storage'


class TestStorageCephChecksBase(StorageTestsBase):

    def test_release_name(self):
        release_name = ceph_core.CephChecksBase().release_name
        self.assertEqual(release_name, 'octopus')

    def test_health_status(self):
        health = ceph_core.CephChecksBase().health_status
        self.assertEqual(health, 'HEALTH_WARN')

    def test_bluestore_enabled(self):
        enabled = ceph_core.CephChecksBase().bluestore_enabled
        self.assertTrue(enabled)

    def test_bluestore_not_enabled(self):
        with tempfile.TemporaryDirectory() as dtmp:
            path = os.path.join(dtmp, 'etc/ceph')
            os.makedirs(path)
            with open(os.path.join(path, 'ceph.conf'), 'w') as fd:
                fd.write(CEPH_CONF_NO_BLUESTORE)

            os.environ['DATA_ROOT'] = dtmp
            enabled = ceph_core.CephChecksBase().bluestore_enabled
            self.assertFalse(enabled)

    def test_check_osdmaps_size(self):
        self.assertEqual(ceph_core.CephMon().osdmaps_count, 5496)


class TestStorageCephDaemons(StorageTestsBase):

    def test_osd_versions(self):
        versions = ceph_core.CephOSD(1, 1234, '/dev/foo').versions
        self.assertEqual(versions, {'15.2.13': 3})

    def test_mon_versions(self):
        versions = ceph_core.CephMon().versions
        self.assertEqual(versions, {'15.2.13': 1})

    def test_mds_versions(self):
        versions = ceph_core.CephMDS().versions
        self.assertEqual(versions, {})

    def test_rgw_versions(self):
        versions = ceph_core.CephRGW().versions
        self.assertEqual(versions, {})

    def test_osd_release_name(self):
        release_names = ceph_core.CephOSD(1, 1234, '/dev/foo').release_names
        self.assertEqual(release_names, {'octopus': 3})

    def test_mon_release_name(self):
        release_names = ceph_core.CephMon().release_names
        self.assertEqual(release_names, {'octopus': 1})


class TestStorageCephServiceInfo(StorageTestsBase):

    def test_get_service_info(self):
        svc_info = {'systemd': {'enabled': [
                                    'ceph-crash',
                                    'ceph-osd',
                                    ],
                                'disabled': [
                                    'ceph-mds',
                                    'ceph-mgr',
                                    'ceph-mon',
                                    'ceph-radosgw',
                                    ],
                                'indirect': ['ceph-volume'],
                                'generated': ['radosgw']},
                    'ps': ['ceph-crash (1)', 'ceph-osd (1)']}
        expected = {'ceph': {
                        'network': {
                            'cluster': {
                                'br-ens3': {
                                    'addresses': ['10.0.0.49'],
                                    'hwaddr': '52:54:00:e2:28:a3',
                                    'state': 'UP',
                                    'speed': 'unknown'}},
                            'public': {
                                'br-ens3': {
                                    'addresses': ['10.0.0.49'],
                                    'hwaddr': '52:54:00:e2:28:a3',
                                    'state': 'UP',
                                    'speed': 'unknown'}}
                            },
                        'services': svc_info,
                        'release': 'octopus',
                        'status': 'HEALTH_WARN',
                    }}
        inst = ceph_service_info.CephServiceChecks()
        inst()
        self.assertEqual(inst.output, expected)

    @mock.patch.object(checks, 'CLIHelper')
    def test_get_service_info_unavailable(self, mock_helper):
        expected = {'ceph': {
                        'network': {
                            'cluster': {
                                'br-ens3': {
                                    'addresses': ['10.0.0.49'],
                                    'hwaddr': '52:54:00:e2:28:a3',
                                    'state': 'UP',
                                    'speed': 'unknown'}},
                            'public': {
                                'br-ens3': {
                                    'addresses': ['10.0.0.49'],
                                    'hwaddr': '52:54:00:e2:28:a3',
                                    'state': 'UP',
                                    'speed': 'unknown'}}
                            },
                        'release': 'unknown',
                        'status': 'HEALTH_WARN'}}

        mock_helper.return_value = mock.MagicMock()
        mock_helper.return_value.ps.return_value = []
        mock_helper.return_value.dpkg_l.return_value = []
        inst = ceph_service_info.CephServiceChecks()
        inst()
        self.assertEqual(inst.output, expected)

    def test_get_package_info(self):
        inst = ceph_service_info.CephPackageChecks()
        inst()
        expected = ['ceph 15.2.13-0ubuntu0.20.04.1',
                    'ceph-base 15.2.13-0ubuntu0.20.04.1',
                    'ceph-common 15.2.13-0ubuntu0.20.04.1',
                    'ceph-mds 15.2.13-0ubuntu0.20.04.1',
                    'ceph-mgr 15.2.13-0ubuntu0.20.04.1',
                    'ceph-mgr-modules-core 15.2.13-0ubuntu0.20.04.1',
                    'ceph-mon 15.2.13-0ubuntu0.20.04.1',
                    'ceph-osd 15.2.13-0ubuntu0.20.04.1',
                    'python3-ceph-argparse 15.2.13-0ubuntu0.20.04.1',
                    'python3-ceph-common 15.2.13-0ubuntu0.20.04.1',
                    'python3-cephfs 15.2.13-0ubuntu0.20.04.1',
                    'python3-rados 15.2.13-0ubuntu0.20.04.1',
                    'python3-rbd 15.2.13-0ubuntu0.20.04.1',
                    'radosgw 15.2.13-0ubuntu0.20.04.1']
        self.assertEquals(inst.output["ceph"]["dpkg"], expected)

    def test_ceph_base_interfaces(self):
        expected = {'cluster': {'br-ens3': {'addresses': ['10.0.0.49'],
                                            'hwaddr': '52:54:00:e2:28:a3',
                                            'state': 'UP',
                                            'speed': 'unknown'}},
                    'public': {'br-ens3': {'addresses': ['10.0.0.49'],
                                           'hwaddr': '52:54:00:e2:28:a3',
                                           'state': 'UP',
                                           'speed': 'unknown'}}}
        ports = ceph_core.CephChecksBase().bind_interfaces
        _ports = {}
        for config, port in ports.items():
            _ports.update({config: port.to_dict()})

        self.assertEqual(_ports, expected)


class TestStorageCephClusterChecks(StorageTestsBase):

    @mock.patch.object(ceph_cluster_checks, 'issue_utils')
    def test_superblock_read_error(self, mock_issue_utils):
        inst = ceph_cluster_checks.CephClusterChecks()
        inst()
        self.assertTrue(mock_issue_utils.add_issue.called)

    @mock.patch.object(ceph_cluster_checks, 'issue_utils')
    def test_check_crushmap_equal_buckets(self, mock_issue_utils):
        inst = ceph_cluster_checks.CephClusterChecks()
        inst.check_crushmap_equal_buckets()
        self.assertFalse(mock_issue_utils.add_issue.called)

    @mock.patch.object(ceph_cluster_checks, 'issue_utils')
    def test_check_crushmap_non_equal_buckets(self, mock_issue_utils):
        '''
        Verifies that the check_crushmap_equal_buckets() function
        correctly raises an issue against a known bad CRUSH map.
        '''
        test_data_path = ('sos_commands/ceph/json_output/'
                          'ceph_osd_crush_dump_--format_'
                          'json-pretty.unbalanced')
        osd_crush_dump_path = os.path.join(os.environ["DATA_ROOT"],
                                           test_data_path)
        osd_crush_dump = json.load(open(osd_crush_dump_path))
        with mock.patch.object(ceph_core, 'CLIHelper') as mock_helper:
            mock_helper.return_value = mock.MagicMock()
            mock_helper.return_value.ceph_osd_crush_dump_json_decoded.\
                return_value = osd_crush_dump
            inst = ceph_cluster_checks.CephClusterChecks()
            inst.check_crushmap_equal_buckets()
            self.assertTrue(mock_issue_utils.add_issue.called)

    @mock.patch.object(ceph_cluster_checks, 'issue_utils')
    def test_get_crushmap_mixed_buckets(self, mock_issue_utils):
        '''
        Verifies that the check_crushmap_equal_buckets() function
        correctly does not raise an issue against a known good CRUSH map.
        '''
        with mock.patch.object(ceph_core, 'CLIHelper') as mock_helper:
            mock_helper.return_value = mock.MagicMock()
            mock_helper.return_value.ceph_osd_crush_dump_json_decoded.\
                return_value = json.loads(CEPH_OSD_CRUSH_DUMP)
            inst = ceph_cluster_checks.CephClusterChecks()
            inst.get_crushmap_mixed_buckets()
            self.assertTrue(mock_issue_utils.add_issue.called)

    @mock.patch.object(ceph_cluster_checks, 'issue_utils')
    def test_get_crushmap_no_mixed_buckets(self, mock_issue_utils):
        inst = ceph_cluster_checks.CephClusterChecks()
        inst.get_crushmap_mixed_buckets()
        self.assertFalse(mock_issue_utils.add_issue.called)

    def test_get_ceph_versions_mismatch_pass(self):
        result = {'mgr': ['15.2.13'],
                  'mon': ['15.2.13'],
                  'osd': ['15.2.13']}
        inst = ceph_cluster_checks.CephClusterChecks()
        inst.get_ceph_versions_mismatch()
        self.assertEqual(inst.output["ceph"]["versions"], result)

    def test_get_ceph_versions_mismatch_fail(self):
        result = {'mgr': ['15.2.11'],
                  'mon': ['15.2.11'],
                  'osd': ['15.2.11',
                          '15.2.13']}
        with mock.patch.object(ceph_core, 'CLIHelper') as mock_helper:
            mock_helper.return_value = mock.MagicMock()
            mock_helper.return_value.ceph_versions.return_value = \
                CEPH_VERSIONS_MISMATCHED_MINOR.split('\n')
            inst = ceph_cluster_checks.CephClusterChecks()
            inst.get_ceph_versions_mismatch()
            self.assertEqual(inst.output["ceph"]["versions"], result)

    @mock.patch.object(ceph_cluster_checks.issue_utils, "add_issue")
    def test_get_ceph_mon_lower_version(self, mock_add_issue):
        issues = []

        def fake_add_issue(issue):
            issues.append(issue)

        mock_add_issue.side_effect = fake_add_issue
        with mock.patch.object(ceph_core, 'CLIHelper') as mock_helper:
            mock_helper.return_value = mock.MagicMock()
            mock_helper.return_value.ceph_versions.return_value = \
                CEPH_VERSIONS_MISMATCHED_MINOR.split('\n')
            inst = ceph_cluster_checks.CephClusterChecks()
            inst.get_ceph_versions_mismatch()

        types = {}
        for issue in issues:
            t = type(issue)
            if t in types:
                types[t] += 1
            else:
                types[t] = 1

        self.assertEqual(types[issue_types.CephDaemonVersionsError], 1)
        self.assertTrue(mock_add_issue.called)

    @mock.patch.object(ceph_core, 'CLIHelper')
    def test_get_ceph_versions_mismatch_unavailable(self, mock_helper):
        mock_helper.return_value = mock.MagicMock()
        mock_helper.return_value.ceph_versions.return_value = []
        inst = ceph_cluster_checks.CephClusterChecks()
        inst.get_ceph_versions_mismatch()
        self.assertIsNone(inst.output)

    @mock.patch.object(ceph_cluster_checks, 'issue_utils')
    def test_check_require_osd_release(self, mock_issue_utils):
        osd_dump = ceph_core.CLIHelper().ceph_osd_dump_json_decoded()
        with mock.patch.object(ceph_core, 'CLIHelper') as mock_helper:
            mock_helper.return_value = mock.MagicMock()
            mock_helper.return_value.ceph_versions.return_value = \
                CEPH_VERSIONS_MISMATCHED_MAJOR.split('\n')
            mock_helper.return_value.ceph_osd_dump_json_decoded.\
                return_value = osd_dump
            inst = ceph_cluster_checks.CephClusterChecks()
            inst.check_require_osd_release()
            self.assertTrue(mock_issue_utils.add_issue.called)

    @mock.patch.object(ceph_cluster_checks, 'issue_utils')
    def test_check_osd_v2(self, mock_issue_utils):
        with tempfile.TemporaryDirectory() as dtmp:
            src = os.path.join(constants.DATA_ROOT,
                               ('sos_commands/ceph/json_output/ceph_osd_dump_'
                                '--format_json-pretty.v1_only_osds'))
            dst = os.path.join(dtmp, 'sos_commands/ceph/json_output/'
                               'ceph_osd_dump_--format_json-pretty')
            os.makedirs(os.path.dirname(dst))
            shutil.copy(src, dst)
            os.environ['DATA_ROOT'] = dtmp
            inst = ceph_cluster_checks.CephClusterChecks()
            inst.check_osd_msgr_protocol_versions()
            self.assertTrue(mock_issue_utils.add_issue.called)

    @mock.patch.object(ceph_cluster_checks, 'issue_utils')
    def test_check_ceph_bluefs_size(self, mock_issue_utils):
        inst = ceph_cluster_checks.CephClusterChecks()
        inst.check_ceph_bluefs_size()
        self.assertTrue(mock_issue_utils.add_issue.called)

    @mock.patch.object(ceph_cluster_checks.issue_utils, "add_issue")
    def test_get_ceph_pg_imbalance(self, mock_add_issue):
        issues = []

        def fake_add_issue(issue):
            issues.append(issue)

        mock_add_issue.side_effect = fake_add_issue
        result = {'osd-pgs-suboptimal': {
                   'osd.0': 295,
                   'osd.1': 501},
                  'osd-pgs-near-limit': {
                      'osd.1': 501}
                  }
        inst = ceph_cluster_checks.CephClusterChecks()
        inst.get_ceph_pg_imbalance()
        self.assertEqual(inst.output["ceph"], result)

        types = {}
        for issue in issues:
            t = type(issue)
            if t in types:
                types[t] += 1
            else:
                types[t] = 1

        self.assertEqual(len(issues), 2)
        self.assertEqual(types[issue_types.CephCrushError], 1)
        self.assertEqual(types[issue_types.CephCrushWarning], 1)
        self.assertTrue(mock_add_issue.called)

    def test_get_osd_ids(self):
        inst = ceph_cluster_checks.CephClusterChecks()
        inst()
        self.assertEqual([osd.id for osd in inst.local_osds], [0])

    def test_get_cluster_osd_ids(self):
        inst = ceph_cluster_checks.CephClusterChecks()
        inst()
        self.assertEqual([osd.id for osd in inst.cluster_osds], [0, 1, 2])

    @mock.patch.object(ceph_core, 'CLIHelper')
    def test_get_ceph_pg_imbalance_unavailable(self, mock_helper):
        mock_helper.return_value = mock.MagicMock()
        mock_helper.return_value.ceph_osd_df_tree.return_value = []
        inst = ceph_cluster_checks.CephClusterChecks()
        inst.get_ceph_pg_imbalance()
        self.assertEqual(inst.output, None)

    def test_get_osd_info(self):
        fsid = "51f1b834-3c8f-4cd1-8c0a-81a6f75ba2ea"
        expected = {0: {
                    'dev': '/dev/mapper/crypt-{}'.format(fsid),
                    'devtype': 'ssd',
                    'fsid': fsid,
                    'rss': '639M'}}
        inst = ceph_cluster_checks.CephClusterChecks()
        inst()
        self.assertEqual(inst.output["ceph"]["local-osds"], expected)

    def test_get_crush_rules(self):
        inst = ceph_cluster_checks.CephClusterChecks()
        inst()
        expected = {'replicated_rule': {'id': 0, 'type': 'replicated',
                    'pools': ['device_health_metrics (1)', 'glance (2)']}}
        self.assertEqual(inst.crush_rules, expected)

    @mock.patch.object(ceph_cluster_checks, 'KernelChecksBase')
    @mock.patch.object(ceph_cluster_checks.bcache, 'BcacheChecksBase')
    @mock.patch.object(ceph_cluster_checks.issue_utils, "add_issue")
    def test_check_bcache_vulnerabilities(self, mock_add_issue, mock_bcb,
                                          mock_kcb):
        mock_kcb.return_value = mock.MagicMock()
        mock_kcb.return_value.version = '5.3'
        mock_cset = mock.MagicMock()
        mock_cset.get.return_value = 60
        mock_bcb.get_sysfs_cachesets.return_value = mock_cset
        inst = ceph_cluster_checks.CephClusterChecks()
        with mock.patch.object(inst, 'is_bcache_device') as mock_ibd:
            mock_ibd.return_value = True
            with mock.patch.object(inst, 'apt_check') as mock_apt_check:
                mock_apt_check.get_version.return_value = "15.2.13"
                inst.check_bcache_vulnerabilities()
                self.assertTrue(mock_add_issue.called)

    @mock.patch.object(ceph_cluster_checks.issue_utils, 'add_issue')
    def test_check_laggy_pgs_no_issue(self, mock_add_issue):
        inst = ceph_cluster_checks.CephClusterChecks()
        inst.check_laggy_pgs()
        self.assertFalse(mock_add_issue.called)

    @mock.patch('core.plugins.storage.ceph.CLIHelper')
    @mock.patch.object(ceph_cluster_checks.issue_utils, 'add_issue')
    def test_check_laggy_pgs_w_issue(self, mock_add_issue, mock_cli):
        mock_cli.return_value = mock.MagicMock()
        mock_cli.return_value.ceph_pg_dump_json_decoded.return_value = \
            PG_DUMP_JSON_DECODED
        inst = ceph_cluster_checks.CephClusterChecks()
        inst.check_laggy_pgs()
        self.assertTrue(mock_add_issue.called)

    @mock.patch.object(ceph_cluster_checks.issue_utils, 'add_issue')
    def test_check_large_omap_objects_no_issue(self, mock_add_issue):
        inst = ceph_cluster_checks.CephClusterChecks()
        inst.check_large_omap_objects()
        self.assertFalse(mock_add_issue.called)

    @mock.patch('core.plugins.storage.ceph.CLIHelper')
    @mock.patch.object(ceph_cluster_checks.issue_utils, 'add_issue')
    def test_check_large_omap_objects_w_issue(self, mock_add_issue, mock_cli):
        mock_cli.return_value = mock.MagicMock()
        mock_cli.return_value.ceph_pg_dump_json_decoded.return_value = \
            PG_DUMP_JSON_DECODED
        inst = ceph_cluster_checks.CephClusterChecks()
        inst.check_large_omap_objects()
        self.assertTrue(mock_add_issue.called)


class TestStorageBcache(StorageTestsBase):

    def test_get_bcache_dev_info(self):
        result = {'bcache': {
                    'devices': {
                        'bcache': {'bcache0': {'dname': 'bcache1'},
                                   'bcache1': {'dname': 'bcache0'}}
                        }}}

        inst = bcache.BcacheDeviceChecks()
        inst()
        self.assertEqual(inst.output, result)

    def test_get_bcache_stats_checks(self):
        self.maxDiff = None
        expected = {'bcache': {
                        'cachesets': [{
                            'cache_available_percent': 95,
                            'uuid': '2bb274af-a015-4496-9455-43393ea06aa2'}]
                        }
                    }
        inst = bcache.BcacheCSetChecks()
        inst()
        self.assertEqual(inst.output, expected)


class TestStorageBugChecks(StorageTestsBase):

    @mock.patch('core.ycheck.bugs.add_known_bug')
    def test_bug_checks(self, mock_add_known_bug):
        bugs = []

        def fake_add_bug(*args, **kwargs):
            bugs.append((args, kwargs))

        mock_add_known_bug.side_effect = fake_add_bug
        YBugChecker()()
        # This will need modifying once we have some storage bugs defined
        self.assertFalse(mock_add_known_bug.called)
        self.assertEqual(len(bugs), 0)


class TestStorageCephEventChecks(StorageTestsBase):

    def test_get_ceph_daemon_log_checker(self):
        result = {'osd-reported-failed': {'osd.41': {'2021-02-13': 23},
                                          'osd.85': {'2021-02-13': 4}},
                  'crc-err-bluestore': {'2021-02-12': 5, '2021-02-13': 1,
                                        '2021-04-01': 2},
                  'crc-err-rocksdb': {'2021-02-12': 7},
                  'long-heartbeat-pings': {'2021-02-09': 42},
                  'heartbeat-no-reply': {'2021-02-09': {'osd.0': 1,
                                                        'osd.1': 2}}}
        inst = ceph_event_checks.CephDaemonLogChecks()
        inst()
        self.assertEqual(inst.output["ceph"], result)


class TestStorageConfigChecks(StorageTestsBase):

    def setup_bcachefs(self, path, error=False):
        cset = os.path.join(path, 'sys/fs/bcache/1234')
        os.makedirs(cset)
        for cfg, val in {'congested_read_threshold_us': '0',
                         'congested_write_threshold_us': '0'}.items():
            with open(os.path.join(cset, cfg), 'w') as fd:
                fd.write(val)

        for cfg, val in {'cache_available_percent': '34'}.items():
            if error:
                if cfg == 'cache_available_percent':
                    # i.e. >= 33 for lplp1900438 check
                    val = '33'

            with open(os.path.join(cset, cfg), 'w') as fd:
                fd.write(val)

        bdev = os.path.join(cset, 'bdev1')
        os.makedirs(bdev)
        for cfg, val in {'sequential_cutoff': '0.0k',
                         'cache_mode':
                         'writethrough [writeback] writearound none',
                         'writeback_percent': '10'}.items():
            if error:
                if cfg == 'writeback_percent':
                    val = '1'

            with open(os.path.join(bdev, cfg), 'w') as fd:
                fd.write(val)

    @mock.patch('core.issues.issue_utils.add_issue')
    def test_config_checks_has_issue(self, mock_add_issue):
        issues = []

        def fake_add_issue(issue):
            issues.append(type(issue))

        mock_add_issue.side_effect = fake_add_issue
        ceph_conf = ceph_core.CephConfig().dump
        with tempfile.TemporaryDirectory() as dtmp:
            os.makedirs(os.path.join(dtmp, 'etc/ceph'))
            with open(os.path.join(dtmp, 'etc/ceph/ceph.conf'), 'w') as fd:
                fd.write(ceph_conf)

            self.setup_bcachefs(dtmp, error=True)
            os.environ['DATA_ROOT'] = dtmp
            YConfigChecker()()
            self.assertTrue(mock_add_issue.called)
            self.assertEquals(issues, [issue_types.BcacheWarning,
                                       issue_types.BcacheWarning])

    @mock.patch('core.issues.issue_utils.add_issue')
    def test_config_checks_no_issue(self, mock_add_issue):
        ceph_conf = ceph_core.CephConfig().dump
        with tempfile.TemporaryDirectory() as dtmp:
            os.makedirs(os.path.join(dtmp, 'etc/ceph'))
            with open(os.path.join(dtmp, 'etc/ceph/ceph.conf'), 'w') as fd:
                fd.write(ceph_conf)

            self.setup_bcachefs(dtmp)
            os.environ['DATA_ROOT'] = dtmp
            YConfigChecker()()
            self.assertFalse(mock_add_issue.called)

    @mock.patch('core.issues.issue_utils.add_issue')
    def test_bcache_unit(self, mock_add_issue):
        issues = []

        def fake_add_issue(issue):
            issues.append(issue)

        mock_add_issue.side_effect = fake_add_issue
        inst = bcache.BcacheCharmChecks()
        inst()
        self.assertEqual(len(issues), 1)
        self.assertEqual(type(issues[0]), issue_types.BcacheWarning)
        self.assertTrue(mock_add_issue.called)


class TestStorageScenarioChecks(StorageTestsBase):

    @mock.patch('core.issues.issue_utils.add_issue')
    def test_scenarios_none(self, mock_add_issue):
        with tempfile.TemporaryDirectory() as dtmp:
            os.environ['DATA_ROOT'] = dtmp
            YScenarioChecker()()
            self.assertFalse(mock_add_issue.called)

    @mock.patch('core.ycheck.scenarios.ScenarioCheck.result',
                lambda args: False)
    @mock.patch('core.plugins.storage.bcache.BcacheChecksBase.plugin_runnable',
                False)
    @mock.patch('core.plugins.storage.ceph.CephChecksBase')
    @mock.patch('core.issues.issue_utils.add_issue')
    def test_scenarios_w_issue(self, add_issue, mock_cephbase):
        issues = []

        def fake_add_issue(issue):
            issues.append(issue)

        add_issue.side_effect = fake_add_issue
        mock_cephbase.return_value = mock.MagicMock()
        mock_cephbase.return_value.has_interface_errors = True
        mock_cephbase.return_value.bind_interface_names = 'ethX'

        # First check not runnable
        mock_cephbase.return_value.plugin_runnable = False
        YScenarioChecker()()
        self.assertFalse(add_issue.called)

        # now runnable
        mock_cephbase.return_value.plugin_runnable = True
        YScenarioChecker()()
        self.assertTrue(add_issue.called)

        msgs = [issue.msg for issue in issues]
        msg = ("Ceph monitor is experiencing repeated re-elections. The "
               "network interface(s) (ethX) used by the ceph-mon are "
               "showing errors - please investigate.")
        self.assertTrue(msg in msgs)

        msg = ("Found 5496 pinned osdmaps. This can affect mon's performance "
               "and also indicate bugs such as https://tracker.ceph.com/"
               "issues/44184 and https://tracker.ceph.com/issues/47290.")
        self.assertTrue(msg in msgs)

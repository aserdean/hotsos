import re

from core.ycheck import CallbackHelper
from core.searchtools import FileSearcher
from core.issues import (
    issue_types,
    issue_utils,
)
from core.plugins.openvswitch import (
    OpenvSwitchEventChecksBase,
)

YAML_PRIORITY = 1
EVENTCALLBACKS = CallbackHelper()


class OpenvSwitchDaemonEventChecks(OpenvSwitchEventChecksBase):

    def __init__(self):
        super().__init__(yaml_defs_group='daemon-checks',
                         searchobj=FileSearcher(),
                         event_results_output_key='daemon-checks',
                         callback_helper=EVENTCALLBACKS)

    @EVENTCALLBACKS.callback
    def netdev_linux_no_such_device(self, event):
        """ Group with vswitchd section results. """
        ret = self.get_results_stats(event.results)
        if ret:
            return {event.name: ret}, 'ovs-vswitchd'

    @EVENTCALLBACKS.callback
    def bridge_no_such_device(self, event):
        """ Group with vswitchd section results. """
        ret = self.get_results_stats(event.results)
        if ret:
            return {event.name: ret}, 'ovs-vswitchd'

    @EVENTCALLBACKS.callback
    def ovs_thread_unreasonably_long_poll_interval(self, event):
        ret = self.get_results_stats(event.results)
        if ret:
            return {event.name: ret}, 'logs'

    @EVENTCALLBACKS.callback
    def rx_packet_on_unassociated_datapath_port(self, event):
        ret = self.get_results_stats(event.results)
        if ret:
            return {event.name: ret}, 'logs'

    @EVENTCALLBACKS.callback
    def receive_tunnel_port_not_found(self, event):
        ret = self.get_results_stats(event.results)
        if ret:
            return {event.name: ret}, 'logs'

    @EVENTCALLBACKS.callback
    def ovs_vswitchd(self, event):
        """ Group with errors-and-warnings section results. """
        ret = self.get_results_stats(event.results, key_by_date=False)
        if ret:
            return {event.name: ret}, 'logs'

    @EVENTCALLBACKS.callback
    def ovsdb_server(self, event):
        """ Group with errors-and-warnings section results. """
        ret = self.get_results_stats(event.results, key_by_date=False)
        if ret:
            return {event.name: ret}, 'logs'


class OpenvSwitchFlowEventChecks(OpenvSwitchEventChecksBase):

    def __init__(self):
        super().__init__(yaml_defs_group='flow-checks',
                         searchobj=FileSearcher(),
                         event_results_output_key='flow-checks',
                         callback_helper=EVENTCALLBACKS)

    @EVENTCALLBACKS.callback
    def deferred_action_limit_reached(self, event):
        ret = self.get_results_stats(event.results, key_by_date=False)
        output_key = "{}-{}".format(event.section, event.name)
        return ret, output_key

    @EVENTCALLBACKS.callback
    def lookups(self, event):
        # expect one line/result
        result = event.results[0]
        lost_packets = int(result.get(3))
        if lost_packets > 0:
            msg = ("ovs datapath is reporting a non-zero amount of \"lost\" "
                   "packets ({}) which implies that packets destined for "
                   "userspace (e.g. vm tap) are being dropped - see "
                   "ovs-appctl dpctl/show.".format(lost_packets))
            issue_utils.add_issue(issue_types.OpenvSwitchWarning(msg))

    @EVENTCALLBACKS.callback
    def port_stats(self, event):
        """
        Report on interfaces that are showing packet drops or errors.

        Sometimes it is normal for an interface to have packet drops and if
        we think that is the case we ignore but otherwise we raise an issue
        to alert.

        Interfaces we currently ignore:

        OVS bridges.

        In Openstack for example when using Neutron HA routers, vrrp peers
        that are in BACKUP state may still receive packets on their external
        interface but these will be dropped since they have no where to go. In
        this case it is possible to have 100% packet drops on the interface
        if that VR has never been a vrrp MASTER. For this scenario we filter
        interfaces whose name matches e.g. qg-3ca935f4-07.
        """
        stats = {}
        all_dropped = []  # interfaces where all packets are dropped
        all_errors = []  # interfaces where all packets are errors
        for section in event.results:
            port = None
            _stats = {}
            for result in section:
                if result.tag == event.sequence_def.start_tag:
                    port = result.get(1)
                elif result.tag == event.sequence_def.body_tag:
                    key = result.get(1)
                    packets = int(result.get(2))
                    errors = int(result.get(3))
                    dropped = int(result.get(4))

                    log_stats = False
                    if packets:
                        dropped_pcent = int((100/packets) * dropped)
                        errors_pcent = int((100/packets) * errors)
                        if dropped_pcent > 1 or errors_pcent > 1:
                            log_stats = True
                    elif errors or dropped:
                        log_stats = True

                    if log_stats:
                        _stats[key] = {"packets": packets}
                        if errors:
                            _stats[key]["errors"] = errors
                        if dropped:
                            _stats[key]["dropped"] = dropped

            if port and _stats:
                # Ports to ignore - see docstring for info
                if (port in [b.name for b in self.bridges] or
                        re.compile(r"^(q|s)g-\S{11}$").match(port)):
                    continue

                for key in _stats:
                    s = _stats[key]
                    if s.get('dropped') and not s['packets']:
                        all_dropped.append(port)

                    if s.get('errors') and not s['packets']:
                        all_errors.append(port)

                stats[port] = _stats

        if stats:
            if all_dropped:
                msg = ("found {} ovs interfaces with 100% dropped packets."
                       .format(len(all_dropped)))
                issue_utils.add_issue(issue_types.OpenvSwitchWarning(msg))

            if all_errors:
                msg = ("found {} ovs interfaces with 100% packet errors."
                       .format(len(all_errors)))
                issue_utils.add_issue(issue_types.OpenvSwitchWarning(msg))

            stats_sorted = {}
            for k in sorted(stats):
                stats_sorted[k] = stats[k]

            output_key = "{}-port-stats".format(event.section)
            return stats_sorted, output_key

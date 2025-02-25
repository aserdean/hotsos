import os

from core import (
    constants,
    plugintools,
)
from core.issues import (
    issue_types,
    issue_utils,
)
from core.searchtools import (
    SearchDef,
    FileSearcher,
)

YAML_PRIORITY = 0


class SOSReportPluginChecks(plugintools.PluginPartBase):

    def __init__(self):
        super().__init__()
        self.searcher = FileSearcher()

    @property
    def plugin_runnable(self):
        # Always run
        return True

    def check_plugin_timeouts(self):
        if not os.path.exists(os.path.join(constants.DATA_ROOT, 'sos_logs')):
            return

        path = os.path.join(constants.DATA_ROOT, 'sos_logs/ui.log')
        self.searcher.add_search_term(SearchDef(r".* Plugin (\S+) timed out.*",
                                                tag="timeouts"), path=path)
        results = self.searcher.search()
        timeouts = []
        for r in results.find_by_tag("timeouts"):
            plugin = r.get(1)
            timeouts.append(plugin)
            msg = ("sosreport plugin '{}' has timed out and may have "
                   "incomplete data.".format(plugin))
            issue_utils.add_issue(issue_types.SOSReportWarning(msg))

        if timeouts:
            self._output["plugin-timeouts"] = timeouts

    def __call__(self):
        self.check_plugin_timeouts()

from core import constants
from core.log import log
from core.checks import DPKGVersionCompare
from core.known_bugs_utils import add_known_bug
from core.ycheck import (
    YDefsLoader,
    YDefsSection,
    AutoChecksBase,
)
from core.searchtools import FileSearcher, SearchDef


class YBugChecker(AutoChecksBase):
    """
    Class used to identify bugs by matching content from files or commands.
    Searches are defined in defs/bugs.yaml per plugin and run automatically.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, searchobj=FileSearcher(), **kwargs)
        self._bug_defs = None

    def _load_bug_definitions(self):
        """ Load bug search definitions from yaml """
        plugin_bugs = YDefsLoader('bugs').load_plugin_defs()
        if not plugin_bugs:
            return

        ybugchecks = YDefsSection(constants.PLUGIN_NAME, plugin_bugs)
        log.debug("loaded plugin '%s' bugs - sections=%s, events=%s",
                  ybugchecks.name,
                  len(ybugchecks.branch_sections),
                  len(ybugchecks.leaf_sections))
        if ybugchecks.requires and not ybugchecks.requires.passes:
            log.debug("plugin not runnable - skipping bug checks")
            return

        bug_defs = []
        for bug in ybugchecks.leaf_sections:
            bdef = {'bug_id': str(bug.name),
                    'context': bug.context,
                    'settings': bug.settings,
                    'message': bug.raises.message,
                    'message_format_result_groups': bug.raises.format_groups}
            if bug.expr:
                pattern = bug.expr.value
                datasource = bug.input.path
                searchdef = SearchDef(pattern,
                                      tag=bdef['bug_id'],
                                      hint=bug.hint.value)
                bdef['searchdef'] = searchdef
                bdef['datasource'] = datasource

            log.debug("bug=%s path=%s", bdef['bug_id'], bdef.get('datasource'))
            bug_defs.append(bdef)

        self._bug_defs = bug_defs

    @property
    def bug_definitions(self):
        """
        @return: dict of SearchDef objects and datasource for all entries in
        bugs.yaml under _yaml_defs_group.
        """
        if self._bug_defs is not None:
            return self._bug_defs

        self._load_bug_definitions()
        return self._bug_defs

    def load(self):
        if not self.bug_definitions:
            return

        for bugsearch in self.bug_definitions:
            if 'searchdef' in bugsearch:
                self.searchobj.add_search_term(bugsearch['searchdef'],
                                               bugsearch['datasource'])

    def package_has_bugfix(self, pkg_version, versions_affected):
        for item in sorted(versions_affected, key=lambda i: i['min-fixed'],
                           reverse=True):
            min_fixed = item['min-fixed']
            min_broken = item['min-broken']
            lt_fixed = pkg_version < DPKGVersionCompare(min_fixed)
            if min_broken:
                lt_broken = pkg_version < DPKGVersionCompare(min_broken)
            else:
                lt_broken = None

            if lt_broken:
                continue

            if lt_fixed:
                return False
            else:
                return True

        return True

    def get_format_list(self, result_group_indexes, search_result):
        values = []
        for idx in result_group_indexes:
            values.append(search_result.get(idx))

        return values

    def run(self, results):
        if not self.bug_definitions:
            return

        for bugsearch in self.bug_definitions:
            format_dict = {}
            format_list = []
            bug_id = bugsearch['bug_id']
            settings = bugsearch['settings']
            if settings and settings.versions_affected and settings.package:
                pkg = settings.package
                pkg_ver = bugsearch['context'].apt_all.get(pkg)
                if pkg_ver:
                    if self.package_has_bugfix(pkg_ver,
                                               settings.versions_affected):
                        # No need to search since the bug is fixed.
                        log.debug('bug %s already fixed in package %s version '
                                  '%s - skipping check', bug_id, pkg, pkg_ver)
                        continue

                    format_dict = {'package_name': pkg,
                                   'version_current': pkg_ver}
                else:
                    log.debug("package %s not installed - skipping check", pkg)
                    continue

            message = bugsearch['message']
            if 'searchdef' in bugsearch:
                bug_matches = results.find_by_tag(bug_id)
                if not bug_matches:
                    continue

                indexes = bugsearch['message_format_result_groups']
                if indexes:
                    # we only use the first result
                    first_match = bug_matches[0]
                    format_list = self.get_format_list(indexes,
                                                       first_match)

            log.debug("bug %s identified", bug_id)
            if format_list:
                add_known_bug(bug_id, message.format(*format_list))
            elif format_dict:
                log.debug(message.format(**format_dict))
                add_known_bug(bug_id, message.format(**format_dict))
            else:
                add_known_bug(bug_id, message)

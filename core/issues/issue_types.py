class IssueTypeBase(object):
    def __init__(self, msg):
        self.name = self.__class__.__name__
        self.msg = msg


class SystemWarning(IssueTypeBase):
    pass


class KernelError(IssueTypeBase):
    pass


class MemoryWarning(IssueTypeBase):
    pass


class CephWarning(IssueTypeBase):
    pass


class CephHealthWarning(IssueTypeBase):
    pass


class CephCrushWarning(IssueTypeBase):
    pass


class CephCrushError(IssueTypeBase):
    pass


class CephOSDError(IssueTypeBase):
    pass


class CephOSDWarning(IssueTypeBase):
    pass


class CephMapsWarning(IssueTypeBase):
    pass


class CephDaemonWarning(IssueTypeBase):
    pass


class CephDaemonVersionsError(IssueTypeBase):
    pass


class JujuWarning(IssueTypeBase):
    pass


class BcacheWarning(IssueTypeBase):
    pass


class NeutronL3HAWarning(IssueTypeBase):
    pass


class NetworkWarning(IssueTypeBase):
    pass


class RabbitMQWarning(IssueTypeBase):
    pass


class OpenstackWarning(IssueTypeBase):
    pass


class OpenvSwitchWarning(IssueTypeBase):
    pass


class SOSReportWarning(IssueTypeBase):
    pass


class SysCtlWarning(IssueTypeBase):
    pass


class OpenstackError(IssueTypeBase):
    pass


class KubernetesWarning(IssueTypeBase):
    pass

##############################################################################
#
# Copyright (C) Zenoss, Inc. 2013, all rights reserved.
#
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
#
##############################################################################

'''
API interfaces and default implementations.
'''

from zope.interface import implements

from Products.ZenUtils.Ext import DirectRouter, DirectResponse

from Products import Zuul
from Products.Zuul.facades import ZuulFacade
from Products.Zuul.interfaces import IFacade
from Products.Zuul.utils import ZuulMessageFactory as _t


class IAWSFacade(IFacade):
    '''
    Python API interface.
    '''

    def add_ec2account(self, accountname, accesskey, secretkey, collector):
        '''
        Schedule the addition of an EC2 account.
        '''

    def setDeviceClassInfo(self, uid, linux=None, windows=None):
        '''
        Set the device classes into which to discovery the guest device
        devices from Linux and Windows instance platform respectively.
        '''


class AWSFacade(ZuulFacade):
    '''
    Python API implementation.
    '''

    implements(IAWSFacade)

    def add_ec2account(self, accountname, accesskey, secretkey, collector):
        deviceRoot = self._dmd.getDmdRoot("Devices")
        device = deviceRoot.findDeviceByIdExact(accountname)
        if device:
            return False, _t("A device named %s already exists." % accountname)

        devicePath = "/Devices/AWS/EC2"

        dc = self._dmd.Devices.getOrganizer(devicePath)

        account = dc.createInstance(accountname)
        account.setPerformanceMonitor(collector)

        account.ec2accesskey = accesskey
        account.ec2secretkey = secretkey

        # TODO: Create a model job.

        return True

    def setDeviceClassInfo(self, uid, linux=None, windows=None):
        account = self._getObject(uid)

        if not linux:
            linux = None

        if not windows:
            windows = None

        if account.linuxDeviceClass != linux:
            account.linuxDeviceClass = linux

        if account.windowsDeviceClass != windows:
            account.windowsDeviceClass = windows


class AWSRouter(DirectRouter):
    '''
    ExtJS DirectRouter API implementation.
    '''

    def _getFacade(self):
        return Zuul.getFacade('aws', self.context)

    def add_ec2account(self, accountname, accesskey, secretkey, collector):
        success = self._getFacade().add_ec2account(
            accountname, accesskey, secretkey, collector)

        if success:
            return DirectResponse.succeed()
        else:
            return DirectResponse.fail("Failed to add EC2 account")

    def setDeviceClassInfo(self, uid, linux=None, windows=None):
        self._getFacade().setDeviceClassInfo(uid, linux=linux, windows=windows)

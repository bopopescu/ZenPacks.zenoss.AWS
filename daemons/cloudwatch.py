# check rrd files; create/delete
# query metrics, update rrd
# sleep?
import sys
import os
import fcntl
import time
from datetime import datetime, timedelta
import operator
import logging
import rrdtool
logging.basicConfig()
log = logging.getLogger('ec2')
libDir = os.path.join(os.path.dirname(__file__), '../lib')
if os.path.isdir(libDir):
    sys.path.append(libDir)

import boto
logging.getLogger('boto').setLevel(logging.CRITICAL)

FIELD_NAMES = (
    'CPUUtilization',
    'NetworkIn',
    'NetworkOut',
    'DiskReadBytes',
    'DiskWriteBytes',
    'DiskReadOps',
    'DiskWriteOps',
    'EphReadBytes',
    'EphWriteBytes',
    'EphReadOps',
    'EphWriteOps'
)

conn_kwargs = {
    'aws_access_key_id': os.environ.get('AWS_ACCESS_KEY_ID', None),
    'aws_secret_access_key': os.environ.get('AWS_SECRET_ACCESS_KEY', None),
}
cwconn = boto.connect_cloudwatch(**conn_kwargs)
ec2conn = boto.connect_ec2(**conn_kwargs)

_instances = []
_instTypes = {}

def getInstances():
    '''
    Collect all the instances across all the
    systems (east, west, etc.). Leave out 
    terminated instances and None instances
    '''
    ec2conn = boto.connect_ec2(**conn_kwargs)
    ec2instances = []
    regions = ec2conn.get_all_regions()
    for region in regions:
        try:
            conn = region.connect(**conn_kwargs)
            for reservation in conn.get_all_instances():
                ec2instances.append([i for i in reservation.instances
                                     if i.id and i.state != 'terminated'])
        except boto.exception.EC2ResponseError, ex:
            #print "ERROR:%s" % ex.error_message
            continue
    return reduce(lambda x,y:x+y, ec2instances)

def update_instance_data():
    _instances = getInstances()
    instTypes = {}
    for i in _instances:
        if not instTypes.has_key(i.instance_type):
            instTypes[i.instance_type]=None
    _instTypes=instTypes.keys()
    return (_instances,_instTypes)


def check_rrds():
    rrd_path = '/opt/zenoss/perf/Devices/EC2Manager'
    if not os.path.exists(rrd_path):
        os.makedirs(rrd_path)
    # check file for each field
    check_rrd_2(rrd_path)
    # directories for instanceTypes
    for itype in _instTypes:
        check_rrd_2(os.path.join(rrd_path,itype))
    # directories for instances
    for inst in _instances:
        check_rrd_2(os.path.join(rrd_path,inst.id))

rrdtuples = []

def check_rrd_2(path):
    if not os.path.exists(path):
        os.makedirs(path)
    for field in FIELD_NAMES:
        if not os.path.exists(os.path.join(path,field + '.rrd')):
            rrdtuples.append(create_rrd(path,field))

def test(p):
    for i in _instTypes:
        p2=os.path.join(p,i)
        print p2
        check_rrd_2(p2)

def create_rrd(path,field):
    filename = os.path.join(path,field + ".rrd")
    #(rrdtype of COUNTER, GAUGE, DERIVE, ABSOLUTE)
    rrdtype = 'GAUGE'
    rrdspec = 'DS:%s:%s:5:U:U' % (field,rrdtype)
    #(agg_type of AVERAGE, MIN, MAX, ?)
    aggspecs = ['RRA:AVERAGE:0.5:1:50' #,'RRA:AVERAGE:0.5:6:50']
    rrdtool.create('"%s"' % filename,"--step","300",rrdspec,aggspecs)

def buildData(conn, units='', consolidate='Average', seconds=300):
    metlist = conn.list_metrics(namespace='AWS/EC2')
    end = datetime.utcnow()
    start = end - timedelta(seconds=seconds+5)
    mdict = dict()

    for met in metlist:
        mid = getMetricId(met)
        instvalues = mdict.setdefault(mid, [])
        ret = met.query(start, end, consolidate, units, seconds)
	if len(ret) > 0:
        	instvalues.append((met.name, ret[-1][consolidate]))
    return mdict

def collect_instances():
    volumes = getEBSVols(boto.connect_ec2(**conn_kwargs))
    for i in instances:
        output = 'InstanceId:' + i.id
        metrics = conn.list_metrics(dimensions={'InstanceId':i.id})
        if len(metrics) == 0:
            continue
        for m in [m2 for m2 in metrics if m2.name 
                  in ['CPUUtilization','NetworkIn','NetworkOut']]:
            try:
                ret = m.query(start, end, consolidate, units, seconds)
                if len(ret) > 0:
                        output += " %s %0.2f" % (m.name,ret[-1][consolidate])
            except:
                continue
        # get ebs metrics
        try:
            volstats = aggEBSmetrics(conn,volumes[i.id],consolidate, units, seconds)
            for mname in volstats.keys():
                    output += " %s %0.2f" % (mname,volstats[mname])
        except:
                pass
        print output

def collect_types():
    for t in instTypes:
        output = 'InstanceType:' + t
        for m in [m2 for m2 in conn.list_metrics(dimensions={'InstanceType':t})
                      if m2.name in ['CPUUtilization','NetworkIn','NetworkOut']]:
            try:
                    ret = m.query(start, end, consolidate, units, seconds)
                    if len(ret) > 0:
                        output += " %s %0.2f" % (m.name,ret[-1][consolidate])
            except:
                continue
        readOps = 0
        writeOps = 0
        readBytes = 0.0
        writeBytes = 0.0
        for i in [i2 for i2 in instances if i2.instance_type == t]:
            try:
                    volstats = aggEBSmetrics(conn,volumes[i.id],consolidate, units, seconds)
                    readOps += volstats['DiskReadOps']
                    writeOps += volstats['DiskWriteOps']
                    readBytes += volstats['DiskRadBytes']
                    writeBytes += volstats['DiskWriteBytes']
            except:
                    continue
        output += " DiskReadOps %0.2f" % readOps
        output += " DiskWriteOps %0.2f" % writeOps
        output += " DiskReadBytes %0.2f" % readBytes
        output += " DiskWriteBytes %0.2f" % writeBytes
        print output

def aggEBSmetrics(conn,volumes,consolidate,units,seconds):
    runtime = datetime.utcnow()
    readOps = 0
    writeOps = 0
    readBytes = 0.0
    writeBytes = 0.0
    end = datetime.utcnow()
    start = end - timedelta(seconds=600+5)
    for v in volumes:
        mets=[m for m in conn.list_metrics(dimensions={'VolumeId':v.id})
              if m.name in ['VolumeReadOps','VolumeWriteBytes','VolumeReadBytes','VolumeWriteOps']]
        for m in mets:
            ret=query_with_backoff(m,start,end,consolidate,units,seconds)
            if len(ret)>0:
                if m.name == 'VolumeReadOps':
                    readOps += ret[-1][consolidate]
                elif m.name == 'VolumeWriteOps':
                    writeOps += ret[-1][consolidate]
                elif m.name == 'VolumeReadBytes':
                    readBytes += ret[-1][consolidate]
                elif m.name == 'VolumeWriteBytes':
                    writeBytes += ret[-1][consolidate]
    runtime = (datetime.utcnow() - runtime).total_seconds()
    return {'DiskReadOps':readOps,
            'DiskWriteOps':writeOps,
            'DiskReadBytes':readBytes,
            'DiskWriteBytes':writeBytes,'EBSruntime':runtime}

def query_with_backoff(metric,
                       start,
                       end,
                       consolidate,
                       units,
                       seconds):
    delay = 1
    tries = 4
    while(tries>0):
        try:
            ret=metric.query(start,end,consolidate,units,seconds)
            return ret
        except boto.exception.BotoServerError as ex:
            if ex.body.find('Throttling') > -1:
                time.sleep(delay)
                tries -= 1
                delay *= 2
            else:
                raise ex
    return None

def getEBSVols(ec2conn):
    vols=ec2conn.get_all_volumes()
    vols=[v for v in vols if v.attachment_state() == 'attached']
    byInst = {}
    for v in vols:
        k=v.attach_data.instance_id
        byInst[k] = byInst.get(k,[]) + [v]
    return byInst


class cloudwatch():
    instances = []
    metrics = []

    def __init__():
        self.update()

    def update():
        instances = self.getInstances()
        metrics = self.getMetrics()

    def getInstances():
        return []

    def getMetrics():
        return []


def main():
    #_instances,_instTypes = update_instance_data()
    return


if __name__ == '__main__':
    try:
        main()
    except Exception, e:
        log.exception(e)
        sys.stdout.write("CW FAIL: %s\n" % e)
        raise SystemExit(3)
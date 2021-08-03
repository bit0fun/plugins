import os
import shelve
import time
from pyln.testing.fixtures import *  # noqa: F401,F403
from pyln.client import RpcError
from pyln.testing.utils import only_one, wait_for

plugin_path = os.path.join(os.path.dirname(__file__), "datastore.py")

# Test taken from lightning/tests/test_misc.py
def test_datastore(node_factory):
    l1 = node_factory.get_node(options={'plugin': plugin_path})
    time.sleep(5)

    # Starts empty
    assert l1.rpc.listdatastore() == {'datastore': []}
    assert l1.rpc.listdatastore('somekey') == {'datastore': []}

    # Add entries.
    somedata = b'somedata'.hex()
    somedata_expect = {'key': 'somekey',
                       'generation': 0,
                       'hex': somedata,
                       'string': 'somedata'}
    assert l1.rpc.datastore(key='somekey', hex=somedata) == somedata_expect

    assert l1.rpc.listdatastore() == {'datastore': [somedata_expect]}
    assert l1.rpc.listdatastore('somekey') == {'datastore': [somedata_expect]}
    assert l1.rpc.listdatastore('otherkey') == {'datastore': []}

    # Cannot add by default.
    with pytest.raises(RpcError, match='already exists'):
        l1.rpc.datastore(key='somekey', hex=somedata)

    with pytest.raises(RpcError, match='already exists'):
        l1.rpc.datastore(key='somekey', hex=somedata, mode="must-create")

    # But can insist on replace.
    l1.rpc.datastore(key='somekey', hex=somedata[:-4], mode="must-replace")
    assert only_one(l1.rpc.listdatastore('somekey')['datastore'])['hex'] == somedata[:-4]
    # And append works.
    l1.rpc.datastore(key='somekey', hex=somedata[-4:-2], mode="must-append")
    assert only_one(l1.rpc.listdatastore('somekey')['datastore'])['hex'] == somedata[:-2]
    l1.rpc.datastore(key='somekey', hex=somedata[-2:], mode="create-or-append")
    assert only_one(l1.rpc.listdatastore('somekey')['datastore'])['hex'] == somedata

    # Generation will have increased due to three ops above.
    somedata_expect['generation'] += 3
    assert l1.rpc.listdatastore() == {'datastore': [somedata_expect]}

    # Can't replace or append non-existing records if we say not to
    with pytest.raises(RpcError, match='does not exist'):
        l1.rpc.datastore(key='otherkey', hex=somedata, mode="must-replace")

    with pytest.raises(RpcError, match='does not exist'):
        l1.rpc.datastore(key='otherkey', hex=somedata, mode="must-append")

    otherdata = b'otherdata'.hex()
    otherdata_expect = {'key': 'otherkey',
                        'generation': 0,
                        'hex': otherdata,
                        'string': 'otherdata'}
    assert l1.rpc.datastore(key='otherkey', string='otherdata', mode="create-or-append") == otherdata_expect

    assert l1.rpc.listdatastore('somekey') == {'datastore': [somedata_expect]}
    assert l1.rpc.listdatastore('otherkey') == {'datastore': [otherdata_expect]}
    assert l1.rpc.listdatastore('badkey') == {'datastore': []}

    ds = l1.rpc.listdatastore()
    # Order is undefined!
    assert (ds == {'datastore': [somedata_expect, otherdata_expect]}
            or ds == {'datastore': [otherdata_expect, somedata_expect]})

    assert l1.rpc.deldatastore('somekey') == somedata_expect
    assert l1.rpc.listdatastore() == {'datastore': [otherdata_expect]}
    assert l1.rpc.listdatastore('somekey') == {'datastore': []}
    assert l1.rpc.listdatastore('otherkey') == {'datastore': [otherdata_expect]}
    assert l1.rpc.listdatastore('badkey') == {'datastore': []}
    assert l1.rpc.listdatastore() == {'datastore': [otherdata_expect]}

    # if it's not a string, won't print
    badstring_expect = {'key': 'badstring',
                        'generation': 0,
                        'hex': '00'}
    assert l1.rpc.datastore(key='badstring', hex='00') == badstring_expect
    assert l1.rpc.listdatastore('badstring') == {'datastore': [badstring_expect]}
    assert l1.rpc.deldatastore('badstring') == badstring_expect

    # It's persistent
    l1.restart()

    assert l1.rpc.listdatastore() == {'datastore': [otherdata_expect]}

    # We can insist generation match on update.
    with pytest.raises(RpcError, match='generation is different'):
        l1.rpc.datastore(key='otherkey', hex='00', mode='must-replace',
                         generation=otherdata_expect['generation'] + 1)

    otherdata_expect['generation'] += 1
    otherdata_expect['string'] += 'a'
    otherdata_expect['hex'] += '61'
    assert (l1.rpc.datastore(key='otherkey', string='otherdataa',
                             mode='must-replace',
                             generation=otherdata_expect['generation'] - 1)
            == otherdata_expect)
    assert l1.rpc.listdatastore() == {'datastore': [otherdata_expect]}

    # We can insist generation match on delete.
    with pytest.raises(RpcError, match='generation is different'):
        l1.rpc.deldatastore(key='otherkey',
                            generation=otherdata_expect['generation'] + 1)

    assert (l1.rpc.deldatastore(key='otherkey',
                                generation=otherdata_expect['generation'])
            == otherdata_expect)
    assert l1.rpc.listdatastore() == {'datastore': []}


def test_upgrade(node_factory):
    l1 = node_factory.get_node()

    datastore = shelve.open(os.path.join(l1.daemon.lightning_dir, 'regtest', 'datastore.dat'), 'c')
    datastore['foo'] = b'foodata'
    datastore['bar'] = b'bardata'
    datastore.close()

    # This "fails" because it unloads itself.
    try:
        l1.rpc.plugin_start(plugin_path)
    except RpcError:
        pass

    l1.daemon.wait_for_log('Upgrading store to have generation numbers')
    wait_for(lambda: not os.path.exists(os.path.join(l1.daemon.lightning_dir,
                                                     'regtest',
                                                     'datastore.dat')))

    vals = l1.rpc.listdatastore()['datastore']
    assert (vals == [{'key': 'foo',
                      'generation': 0,
                      'hex': b'foodata'.hex(),
                      'string': 'foodata'},
                     {'key': 'bar',
                      'generation': 0,
                      'hex': b'bardata'.hex(),
                      'string': 'bardata'}]
            or vals == [{'key': 'bar',
                         'generation': 0,
                         'hex': b'bardata'.hex(),
                         'string': 'bardata'},
                        {'key': 'foo',
                         'generation': 0,
                         'hex': b'foodata'.hex(),
                         'string': 'foodata'}])

# file is called AST to not collide with std lib module 'ast'
#
# It provides types to build ASTs in a simple lambda-notation style
#

from StringIO import StringIO

class SymbolTable(object):

    def __init__(self):
        # -- list and dict are special because they are Python builtins
        self._impls = {
                'list': list,
                'dict': dict,
                'literal': lambda x: x}

    def _new_apply(self, name, args, kwargs, o_len):
        pos_args = [as_apply(a) for a in args]
        named_args = [(k, as_apply(v)) for (k, v) in kwargs.items()]
        named_args.sort()
        return Apply(name,
                pos_args=pos_args,
                named_args=named_args,
                o_len=o_len)

    def list(self, init):
        return self._new_apply('list', init, {}, o_len=len(init))

    def dict(self, *args, **kwargs):
        # XXX: figure out len
        return self._new_apply('dict', args, kwargs)

    def define(self, f, o_len=None):
        """Decorator for adding python functions to self
        """
        name = f.__name__
        if hasattr(self, name):
            raise ValueError('Cannot override existing symbol', name)
        def apply_f(*args, **kwargs):
            return self._new_apply(name, args, kwargs, o_len)
        setattr(self, name, apply_f)
        self._impls[name] = f
        return f

    def define_info(self, o_len):
        def wrapper(f):
            return self.define(f, o_len=o_len)
        return wrapper


global_scope = SymbolTable()


def as_apply(obj):
    """Smart way of turning object into an Apply
    """
    if isinstance(obj, Apply):
        rval = obj
    elif isinstance(obj, (tuple, list)):
        rval = Apply('list', [as_apply(a) for a in obj], {}, len(obj))
    elif isinstance(obj, dict):
        items = obj.items()
        # -- should be fine to allow numbers and simple things
        #    but think about if it's ok to allow Applys
        #    it messes up sorting at the very least.
        items.sort()
        named_args = [(k, as_apply(v)) for (k, v) in items]
        rval = Apply('dict', [], named_args, len(named_args))
    else:
        rval = Literal(obj)
    assert isinstance(rval, Apply)
    return rval


class Apply(object):
    """
    Represent a symbolic application of a symbol to arguments.
    """

    def __init__(self, name, pos_args, named_args, o_len=None):
        self.name = name
        self.pos_args = pos_args
        self.named_args = named_args
        # -- o_len is attached this early to support tuple unpacking and
        #    list coersion.
        self.o_len = o_len
        assert all(isinstance(v, Apply) for v in pos_args)
        assert all(isinstance(v, Apply) for k, v in named_args)
        assert all(isinstance(k, basestring) for k, v in named_args)

    def inputs(self):
        return self.pos_args + [v for (k, v) in self.named_args]

    def replace_input(self, old_node, new_node):
        rval = []
        for ii, aa in enumerate(self.pos_args):
            if aa is old_node:
                self.pos_args[ii] = new_node
                rval.append(ii)
        for ii, (nn, aa) in enumerate(self.named_args):
            if aa is old_node:
                self.named_args[ii][1] = new_node
                rval.append(ii + len(self.pos_args))
        return rval

    def pprint(self, ofile, indent=0):
        print >> ofile, ' ' * indent + self.name
        for arg in self.pos_args:
            arg.pprint(ofile, indent+2)
        for name, arg in self.named_args:
            print >> ofile, ' ' * indent + ' ' + name + ' ='
            arg.pprint(ofile, indent+2)

    def __str__(self):
        sio = StringIO()
        self.pprint(sio)
        return sio.getvalue()[:-1] # -- remove trailing '\n'

    def __add__(self, other):
        return global_scope.add(self, other)

    def __radd__(self, other):
        return global_scope.add(other, self)

    def __getitem__(self, idx):
        if self.o_len is not None and isinstance(idx, int):
            if idx >= self.o_len:
                #  -- this IndexError is essential for supporting
                #     tuple-unpacking syntax or list coersion of self.
                raise IndexError()
        return global_scope.getitem(self, idx)

    def __len__(self):
        if self.o_len is None:
            return object.__len__(self)
        return self.o_len


class Literal(Apply):
    def __init__(self, obj):
        try:
            o_len = len(obj)
        except TypeError:
            o_len = None
        Apply.__init__(self, 'literal', [], {}, o_len)
        self._obj = obj

    def pprint(self, ofile, indent=0):
        print >> ofile, ' ' * indent + ('Literal{%s}' % str(self._obj))

    def replace_input(self, old_node, new_node):
        return []


def dfs(aa, seq=None, seqset=None):
    if seq is None:
        assert seqset is None
        seq = []
        seqset = set()
    # -- seqset is the set of all nodes we have seen (which may be still on
    #    the stack)
    if aa in seqset:
        return
    seqset.add(aa)
    for ii in aa.inputs():
        dfs(ii, seq, seqset)
    seq.append(aa)
    return seq


implicit_stochastic_symbols = set()


def implicit_stochastic(f):
    implicit_stochastic_symbols.add(f.__name__)
    return f


@global_scope.define_info(o_len=2)
def draw_rng(rng, f_name, *args, **kwargs):
    draw = global_scope.impls[f_name](*args, rng=rng, **kwargs)
    return draw, rng


def replace_implicit_stochastic_nodes(expr, rng, scope=global_scope):
    """
    Make all of the stochastic nodes in expr use the rng

    uniform(0, 1) -> getitem(draw_rng(rng, 'uniform', 0, 1), 1)
    """
    lrng = as_apply(rng)
    nodes = dfs(expr)
    for ii, orig in enumerate(nodes):
        if orig.name in implicit_stochastic_symbols:
            draw, new_lrng = scope.draw_rng(
                    lrng,
                    orig.name,
                    orig.pos_args,
                    orig.named_args)
            # -- loop over all nodes that *use* this one, and change them
            for client in nodes[ii+1:]:
                client.replace(orig, draw, semantics=dict(reason='adding rng'))
            if expr is orig:
                expr = draw
            lrng = new_lrng
    return expr, new_lrng


@global_scope.define
def getitem(obj, idx):
    return obj[idx]


@global_scope.define
def identity(obj):
    return obj


@global_scope.define
def add(a, b):
    return a + b


@implicit_stochastic
@global_scope.define
def uniform(low, high, rng=None):
    rng.uniform(low, high)


@implicit_stochastic
@global_scope.define
def choice(args, rng=None):
    ii = rng.randint(len(args))
    return args[ii]


@implicit_stochastic
@global_scope.define
def quantized_uniform(low, high, q, rng=None):
    draw = rng.uniform(low, high)
    return np.floor(draw/q) * q


@implicit_stochastic
@global_scope.define
def log_uniform(low, high, rng=None):
    loglow = np.log(low)
    loghigh = np.log(high)
    draw = rng.uniform(loglow, loghigh)
    return np.exp(draw)

#
#
#
import numpy as np

def test_literal_pprint():
    l = Literal(5)
    print str(l)
    assert str(l) == 'Literal{5}'


def test_literal_apply():
    l0 = Literal([1, 2, 3])
    print str(l0)
    assert str(l0) == 'Literal{[1, 2, 3]}'

def test_literal_unpacking():
    l0 = Literal([1, 2, 3])
    a, b, c = l0
    print a
    assert c.name == 'getitem'
    assert c.pos_args[0] is l0
    assert isinstance(c.pos_args[1], Literal)
    assert c.pos_args[1]._obj == 2


def test_as_apply_passthrough():
    a4 = as_apply(4)
    assert a4 is as_apply(a4)


def test_as_apply_literal():
    assert isinstance(as_apply(7), Literal)


def test_as_apply_list_of_literals():
    l = [9, 3]
    al = as_apply(l)
    assert isinstance(al, Apply)
    assert al.name == 'list'
    assert len(al) == 2
    assert isinstance(al.pos_args[0], Literal)
    assert isinstance(al.pos_args[1], Literal)
    al.pos_args[0]._obj == 9
    al.pos_args[1]._obj == 3


def test_as_apply_list_of_applies():
    alist = [as_apply(i) for i in range(5)]

    al = as_apply(alist)
    assert isinstance(al, Apply)
    assert al.name == 'list'
    # -- have to come back to this if Literal copies args
    assert al.pos_args == alist


def test_as_apply_dict_of_literals():
    d = {'a': 9, 'b': 10}
    ad = as_apply(d)
    assert isinstance(ad, Apply)
    assert ad.name == 'dict'
    assert len(ad) == 2
    assert ad.named_args[0][0] == 'a'
    assert ad.named_args[0][1]._obj == 9
    assert ad.named_args[1][0] == 'b'
    assert ad.named_args[1][1]._obj == 10


def test_as_apply_dict_of_applies():

    d = {'a': as_apply(9), 'b': as_apply(10)}
    ad = as_apply(d)
    assert isinstance(ad, Apply)
    assert ad.name == 'dict'
    assert len(ad) == 2
    assert ad.named_args[0][0] == 'a'
    assert ad.named_args[0][1]._obj == 9
    assert ad.named_args[1][0] == 'b'
    assert ad.named_args[1][1]._obj == 10


def test_as_apply_nested_dict():
    d = {'a': 9, 'b': {'c':11, 'd':12}}
    ad = as_apply(d)
    assert isinstance(ad, Apply)
    assert ad.name == 'dict'
    assert len(ad) == 2
    assert ad.named_args[0][0] == 'a'
    assert ad.named_args[0][1]._obj == 9
    assert ad.named_args[1][0] == 'b'
    assert ad.named_args[1][1].name == 'dict'
    assert ad.named_args[1][1].named_args[0][0] == 'c'
    assert ad.named_args[1][1].named_args[0][1]._obj == 11
    assert ad.named_args[1][1].named_args[1][0] == 'd'
    assert ad.named_args[1][1].named_args[1][1]._obj == 12


def test_lnorm():
    G = global_scope
    choice = G.choice
    uniform = G.uniform
    quantized_uniform = G.quantized_uniform

    inker_size = quantized_uniform(low=0, high=7.99, q=2) + 3
    # -- test that it runs
    lnorm = as_apply({'kwargs': {'inker_shape' : (inker_size, inker_size),
             'outker_shape' : (inker_size, inker_size),
             'remove_mean' : choice([0, 1]),
             'stretch' : uniform(low=0, high=10),
             'threshold' : uniform(
                 low=.1 / np.sqrt(10.),
                 high=10 * np.sqrt(10))
             }})
    assert len(str(lnorm)) == 977, len(str(lnorm))


def test_dfs():
    dd = as_apply({'c':11, 'd':12})

    d = {'a': 9, 'b': dd, 'y': dd, 'z': dd + 1}
    ad = as_apply(d)
    order = dfs(ad)
    print [str(o) for o in order]
    assert order[0]._obj == 9
    assert order[1]._obj == 11
    assert order[2]._obj == 12
    assert order[3].named_args[0][0] == 'c'
    assert order[4]._obj == 1
    assert order[5].name == 'add'
    assert order[6].named_args[0][0] == 'a'
    assert len(order) == 7


def test_o_len():
    obj = global_scope.draw_rng()
    x, y = obj
    assert x.name == 'getitem'
    assert x.pos_args[1]._obj == 0


def test_replace_implicit_stochastic_nodes():
    a = global_scope.uniform(-2, -1)
    rng = np.random.RandomState(234)
    new_a, lrng = replace_implicit_stochastic_nodes(a, rng)
    print new_a



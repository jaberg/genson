# file is called AST to not collide with std lib module 'ast'
#
# It provides types to build ASTs in a simple lambda-notation style
#

class SymbolTable(object):
    def __init__(self):
        self._impls = {}
    
    def define(self, f):
        """Decorator for adding python functions to self
        """
        # XXX: validation of f.__name__
        name = f.__name__
        def call_f(*args, **kwargs):
            return Call(name, i_args=args, i_kwargs=kwargs)
        setattr(self, name, call_f)
        self._impls[name] = f
        return f

ST = SymbolTable()


def as_call(obj):
    # XXX: consider digging through lists and tuples for
    #  calls, so that if b is a Call, and list(b) is a list of getitems,
    #  that this list is not treated as a literal by a subsequent as_call.
    if isinstance(obj, Call):
        return obj
    else:
        return Literal(obj)


class Call(object):
    """
    Represent a symbolic application of a symbol to arguments.
    """

    def __init__(self, name, i_args, i_kwargs, o_len=None):
        self.name = name
        self.i_args = [as_call(a) for a in i_args]
        self.i_kwargs = dict(*[(k, as_call(v)) for (k, v) in i_kwargs.items()])
        # -- o_len is attached this early to support tuple unpacking and
        #    list coersion.
        self.o_len = o_len
        assert all(isinstance(k, basestring) for k in i_kwargs.keys())

    def inputs(self):
        """Return the arguments to the call in a standard order"""
        kw_items = self.i_kwargs.items()
        kw_items.sort()
        return self.i_args + [v for (k, v) in kw_items]

    def pprint(self, ofile, indent=0):
        print >> ofile, ' ' * indent + self.name
        for arg in self.inputs():
            arg.pprint(ofile, indent+1)

    def __str__(self):
        sio = StringIO()
        self.pprint(sio)
        return sio.getvalue()

    def __add__(self, other):
        return ST.add(self, other)

    def __radd__(self, other):
        return ST.add(other, self)

    def __getitem__(self, idx):
        if self.o_len is not None and isinstance(idx, int):
            if idx >= self.o_len:
                #  -- this IndexError is essential for supporting
                #     tuple-unpacking syntax or list coersion of self.
                raise IndexError
        return ST.getitem(self, idx)

    def __len__(self):
        if self.o_len is None:
            return object.__len__(self)
        return self.o_len


class Literal(Call):
    def __init__(self, obj):
        try:
            o_len = len(obj)
        except TypeError:
            o_len = None
        Call.__init__(self, 'identity', [], {}, o_len)
        self._obj = obj

    def pprint(self, ofile, indent=0):
        print >> ofile, ' ' * indent + ('Literal{%s}' % str(self._obj))


@ST.define
def getitem(obj, idx):
    return obj[idx]

@ST.define
def identity(obj):
    return obj


@ST.define
def uniform(rng, *args, **kwargs):
    return rng.uniform(*args, **kwargs)


from StringIO import StringIO

def test_literal_pprint():
    l = Literal(5)
    print str(l)
    assert str(l) == 'Literal{5}'


def test_literal_call():
    l0 = Literal([1, 2, 3])
    assert str(l0) == 'Literal{[1, 2, 3]}'
    a, b, c = l0
    print a
    assert str(a)


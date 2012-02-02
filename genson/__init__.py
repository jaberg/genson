from parser import *
from internal_ops import lazy
from internal_ops import register_lazy
from internal_ops import register_function
from internal_ops import LazyCall
from internal_ops import GenSONFunction
from internal_ops import GenSONOperand
from references import ref
from functions import *
from util import *
import copy


class JSONGenerator:
    def __init__(self, genson_dict):
        self.genson_dict = genson_dict

        self.generators = []
        self.find_generators(genson_dict)

        self.first_run = True

    def find_generators(self, d):
        if isdict(d):
            vals = d.values()
        elif isiterable(d):
            vals = d
        else:
            raise TypeError('invalid generator document', d)

        for v in vals:
            if isinstance(v, ParameterGenerator):
                self.generators.append(v)
            if isdict(v) or isiterable(v):
                self.find_generators(v)

    def __iter__(self):
        return self

    def advance_generator_stack(self, cursor=0):

        if cursor >= len(self.generators):
            return False

        if self.generators[cursor].advance():
            return True
        else:
            self.generators[cursor].reset()
            return self.advance_generator_stack(cursor + 1)

    def next(self):

        if self.first_run:
            self.first_run = False
            return resolve(self.genson_dict)

        if self.advance_generator_stack():
            return resolve(self.genson_dict)
        else:
            self.first_run = True
            raise StopIteration()

    def reset(self):
        for g in self.generators:
            g.reset()

    # dictionary support
    def __getitem__(self, key):
        return self.genson_dict[key]

    def keys(self):
        return self.genson_dict.keys()


def load(io):
    s = "\n".join(io.readlines())
    return loads(s)


def loads(genson_string):
    parser = GENSONParser()
    genson_dict = parser.parse_string(genson_string)
    return JSONGenerator(genson_dict)


def dumps(generator, pretty_print=False):
    if isdict(generator):
        return genson_dumps(generator, pretty_print)
    else:
        return genson_dumps(generator.genson_dict, pretty_print)


FROM_KWARGS = 'from_kwargs'
FROM_ARGS = 'from_args'

class JSONFunction(object):
    """Make a GenSON document into a callable function
    """
    # TODO: make the treatment of args and kwargs in the document
    #       more Python-like. The current implementation requires that
    #       parameters (and hence arguments as well) be divided between
    #       positional and keyword, which python does not require.

    def __init__(self, prog):
        self.prog = prog

    def __call__(self, *args, **kwargs):
        prog = copy.deepcopy(self.prog)
        cleanup = []
        if args:
            if prog['args'] == FROM_ARGS:
                prog['args'] = args
                cleanup.append('args')
            else:
                raise ValueError(
                    "to accept args, must have prog['args'] == 'calldoc'")
        if kwargs:
            if prog['kwargs'] == FROM_KWARGS:
                prog['kwargs'] = kwargs
                cleanup.append('kwargs')
            else:
                raise ValueError(
                    "to accept kwargs, must have prog['kwargs'] == 'calldoc'")

        # TODO: execute more directly, don't go through generator
        rval_iter = iter(JSONGenerator(prog))
        ii = 0
        # TODO: use itertools enumerate
        for rval in rval_iter:
            ii += 1
            if ii == 2:
                raise ValueError('genson_call is inappropriate for grid programs')
        for key in cleanup:
            del rval[key]
        return rval


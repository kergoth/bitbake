#!/usr/bin/env python
# ex:ts=4:sw=4:sts=4:et
# -*- tab-width: 4; c-basic-offset: 4; indent-tabs-mode: nil -*-
"""
   class for handling configuration data files

   Reads a .conf file and obtains its metadata

"""

# Copyright (C) 2003, 2004  Chris Larson
# Copyright (C) 2003, 2004  Phil Blundell
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 as
# published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

import re, os
import logging
import bb.utils
from cStringIO import StringIO
from bb.parse import ParseError, resolve_file, ast, logger

#__config_regexp__  = re.compile( r"(?P<exp>export\s*)?(?P<var>[a-zA-Z0-9\-_+.${}]+)\s*(?P<colon>:)?(?P<ques>\?)?=\s*(?P<apo>['\"]?)(?P<value>.*)(?P=apo)$")
__config_regexp__  = re.compile( r"(?P<exp>export\s*)?(?P<var>[a-zA-Z0-9\-_+.${}/]+)(\[(?P<flag>[a-zA-Z0-9\-_+.]+)\])?\s*((?P<colon>:=)|(?P<lazyques>\?\?=)|(?P<ques>\?=)|(?P<append>\+=)|(?P<prepend>=\+)|(?P<predot>=\.)|(?P<postdot>\.=)|=)\s*(?P<apo>['\"]?)(?P<value>.*)(?P=apo)$")
__include_regexp__ = re.compile( r"include\s+(.+)" )
__require_regexp__ = re.compile( r"require\s+(.+)" )
__export_regexp__ = re.compile( r"export\s+(.+)" )

def init(data):
    topdir = data.getVar('TOPDIR')
    if not topdir:
        data.setVar('TOPDIR', os.getcwd())


def supports(fn, d):
    return fn[-5:] == ".conf"

def include(oldfn, fn, data, error_out):
    """
    error_out If True a ParseError will be raised if the to be included
    config-files could not be included.
    """
    if oldfn == fn: # prevent infinite recursion
        return None

    import bb
    fn = data.expand(fn)
    oldfn = data.expand(oldfn)

    if not os.path.isabs(fn):
        dname = os.path.dirname(oldfn)
        bbpath = "%s:%s" % (dname, data.getVar("BBPATH", 1))
        abs_fn = bb.utils.which(bbpath, fn)
        if abs_fn:
            fn = abs_fn

    from bb.parse import handle
    try:
        ret = handle(fn, data, True)
    except IOError:
        if error_out:
            raise ParseError("Could not %(error_out)s file %(fn)s" % vars() )
        logger.debug(2, "CONF file '%s' not found", fn)

def handle(filename, d=None, include=False):
    if d is None:
        d = bb.data.init()

    abs_filename = resolve_file(filename, d)

    if include:
        bb.parse.mark_dependency(d, abs_filename)

    with open(abs_filename) as fobj:
        nodes = parse(fobj, filename)

    if include:
        oldfile = d.getVar('FILE')
    else:
        oldfile = None
    d.setVar('FILE', abs_filename)

    nodes.eval(d)

    if oldfile:
        d.setVar('FILE', oldfile)

    return d

def parse_string(string, filename='<string>', lineoffset=0):
    fileobj = StringIO(string)
    return parse(fileobj, filename, lineoffset)

def parse(fileobj, filename='<string>', lineoffset=0):
    statements = ast.StatementGroup()
    content = ""
    for lineno, line in enumerate(fileobj, lineoffset):
        line = line.rstrip()

        if not line.lstrip():
            continue

        if line[0] == '#':
            continue

        if line.endswith('\\'):
            content += line[:-1]
            continue
        elif content:
            line = content + line
            content = ""

        statements.append(parse_line(line, lineno, filename))

    return statements

def parse_line(line, lineno, filename):
    m = __config_regexp__.match(line)
    if m:
        return ast.DataNode(filename, lineno, m.groupdict())

    m = __include_regexp__.match(line)
    if m:
        return ast.IncludeNode(filename, lineno, what_file=m.group(1), force=False)

    m = __require_regexp__.match(line)
    if m:
        return ast.IncludeNode(filename, lineno, what_file=m.group(1), force=True)

    m = __export_regexp__.match(line)
    if m:
        return ast.ExportNode(filename, lineno, var=m.group(1))

    raise ParseError("%s:%d: unparsed line: '%s'" % (filename, lineno, line));

# Add us to the handlers list
from bb.parse import handlers
handlers.append({'supports': supports, 'handle': handle, 'init': init})
del handlers

# ex:ts=4:sw=4:sts=4:et
# -*- tab-width: 4; c-basic-offset: 4; indent-tabs-mode: nil -*-
"""
BitBake 'Fetch' git submodules implementation

Inherits from and extends the Git fetcher to retrieve submodules of a git repository
after cloning.

SRC_URI = "gitsm://<see Git fetcher for syntax>"

See the Git fetcher, git://, for usage documentation.

NOTE: Switching a SRC_URI from "git://" to "gitsm://" requires a clean of your recipe.

"""

# Copyright (C) 2013 Richard Purdie
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

import collections
import os
import bb
from   bb.fetch2.git import Git
from   bb.fetch2 import runfetchcmd
from   bb.fetch2 import logger

class GitSM(Git):
    scheme = 'gitsm'

    def supports(self, ud, d):
        return ud.type == self.scheme

    def uses_submodules(self, ud, d, wd):
        for name in ud.names:
            try:
                runfetchcmd("%s show %s:.gitmodules" % (ud.basecmd, ud.revisions[name]), d, quiet=True, workdir=wd)
                return True
            except bb.fetch.FetchError:
                pass
        return False

    def need_update(self, ud, d):
        if super().need_update(ud, d):
            return True

        if os.path.exists(ud.clonedir) and self.uses_submodules(ud, d, ud.clonedir):
            fetcher = self.create_submodule_fetcher(ud, d)
            for sm_url, sm_ud in fetcher.ud.items():
                if sm_ud.method.need_update(sm_ud, d):
                    return True

        return False

    def download(self, ud, d):
        if super().need_update(ud, d):
            super().download(ud, d)

        if ud.shallow and ud.localpath == ud.fullshallow:
            try:
                submodule_urls = runfetchcmd("tar -xzOf %s ./.git/submodule_urls" % ud.fullshallow, d).splitlines()
            except bb.fetch2.FetchError as exc:
                return
        elif not self.uses_submodules(ud, d, ud.clonedir):
            return
        else:
            submodule_urls = None

        fetcher = self.create_submodule_fetcher(ud, d, submodule_urls)
        fetcher.download()

    def clone_shallow_local(self, ud, dest, d):
        super().clone_shallow_local(ud, dest, d)

        gitdir = runfetchcmd('%s rev-parse --git-dir' % ud.basecmd, d, workdir=dest).rstrip()
        gitdir = os.path.join(dest, gitdir)

        submodule_urls = self.get_submodule_urls(ud, d)
        with open(os.path.join(gitdir, 'submodule_urls'), 'w') as f:
            f.writelines(u + '\n' for u in submodule_urls)

    def unpack(self, ud, destdir, d):
        super().unpack(ud, destdir, d)

        if ud.shallow and (not os.path.exists(ud.clonedir) or self.need_update(ud, d)):
            sm_urls = os.path.join(ud.destdir, '.git', 'submodule_urls')
            if os.path.exists(sm_urls):
                with open(sm_urls, 'r') as f:
                    submodule_urls = f.read().splitlines()
                self.unpack_submodules(ud, d, ud.destdir, submodule_urls)

            if ud.bareclone:
                runfetchcmd("mv .git/* . && rmdir .git", d, workdir=ud.destdir)
        elif self.uses_submodules(ud, d, ud.clonedir):
            self.unpack_submodules(ud, d, ud.destdir)

    def unpack_submodules(self, ud, d, destdir, urls=None):
        gitdir = runfetchcmd('%s rev-parse --git-dir' % ud.basecmd, d, workdir=destdir).rstrip()
        gitdir = os.path.join(destdir, gitdir)
        modulesdir = os.path.join(gitdir, 'modules')

        fetcher = self.create_submodule_fetcher(ud, d, urls)
        fetcher.unpack(modulesdir)

        # We mark these bare to avoid a checkout, but submodules use them
        # as non-bare repos with worktrees, so disable bare
        for ud in fetcher.ud.values():
            sm_dest = os.path.join(modulesdir, ud.parm['destsuffix'])
            runfetchcmd(ud.basecmd + " config core.bare false", d, workdir=sm_dest)

        runfetchcmd(ud.basecmd + " submodule update --init --recursive --no-fetch", d, workdir=destdir)
        runfetchcmd(ud.basecmd + " submodule sync --recursive", d, workdir=destdir)

    def create_submodule_fetcher(self, ud, d, urls=None, revision=None):
        if urls is None:
            urls = list(self.get_submodule_urls(ud, d, revision))
        l = d.createCopy()
        # Avoid conflict with explicit ;rev= in the urls
        l.delVar('SRCREV')
        return bb.fetch.Fetch(urls, l, cache=False)

    def get_submodule_urls(self, ud, d, revision=None):
        if revision is None:
            revision = ud.revisions[ud.names[0]]

        try:
            config_lines = runfetchcmd("%s show %s:.gitmodules | git config -f - -l" % (ud.basecmd, revision), d, workdir=ud.clonedir)
        except bb.fetch.FetchError:
            return

        submodules = collections.defaultdict(dict)
        for line in config_lines.splitlines():
            full_key, value = line.split('=', 1)
            _, sm_name, key = full_key.split('.', 2)
            submodules[sm_name][key] = value

        for sm_name, sm_data in submodules.items():
            tree_info = runfetchcmd("%s ls-tree %s %s" % (ud.basecmd, revision, sm_data['path']), d, workdir=ud.clonedir)
            sm_revision = tree_info.split()[2]

            # Construct a bitbake fetcher url from the git url
            url = sm_data['url']
            try:
                scheme, netloc, path, user, pw, param = bb.fetch.decodeurl(url)
            except bb.fetch.MalformedUrl:
                import re
                # Two valid git remote locations which aren't valid urls: ssh
                # user@host:path and a local path on disk
                m = re.match('^([^/:]+):(.*)', url)
                if m:
                    url = 'ssh://' + m.group(1) + '/' + m.group(2)
                    scheme, netloc, path, user, pw, param = bb.fetch.decodeurl(url)
                else:
                    scheme, netloc, path, user, pw, param = 'file', '', url, '', '', {}

            param['bareclone'] = '1'
            param['protocol'] = scheme
            param['rev'] = sm_revision
            param['destsuffix'] = sm_name + os.sep
            if 'branch' in sm_data:
                param['branch'] = sm_data['branch']
            else:
                param['nobranch'] = '1'

            yield bb.fetch2.encodeurl([self.scheme, netloc, path, user, pw, param])

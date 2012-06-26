#!/usr/bin/python
# -*- coding: latin-1 -*-
"""JPyang: Java output plug-in
 * Copyright (c) 2012 Tail-F Systems AB.
 * Korgmakargränd 2, SE-111 22, Stockholm, Sweden
 * All rights reserved.
 *
 * This software is the confidential and proprietary information of Tail-F
 * Systems AB. ('Confidential Information').  You shall not
 * disclose such Confidential Information and shall use it only in
 * accordance with the terms of the license agreement you entered into
 * with Tail-F Systems AB.
 *
 * To be released under GNU General Public License.
 * Please see http://www.opensource.org/licenses/gpl-3.0.html
 * or http://www.gnu.org/licenses/gpl.html

For complete functionality, invoke with:
> pyang \
    --path <yang search path>
    --format java \
    --java-package <package.name> \
    --jpyang-verbose \
    --jpyang-javadoc <javadoc directory path> \
    <file.yang>

Or, if you like to keep things simple:
> pyang -f jpyang -d <package.name> <file.yang>

"""

from __future__ import with_statement  # Not required from Python 2.6 and
# ... onwards, but kept for the sake of backwards compatibility

import optparse  # FIXME Deprecated in python 2.7, should use argparse instead
# ... See http://stackoverflow.com/questions/3217673/why-use-argparse-rather-
# ... than-optparse and http://docs.python.org/dev/library
# ... /argparse.html#upgrading-optparse-code
import os
import errno
import sys
from inspect import currentframe
import datetime

from pyang import plugin
from pyang import util
from pyang import error
from pyang import statements


def pyang_plugin_init():
    """Registers an instance of the jpyang plugin"""
    plugin.register_plugin(JPyangPlugin())


class JPyangPlugin(plugin.PyangPlugin):
    """The plug-in class of JPyang"""

    def add_output_format(self, fmts):
        """Adds 'java' and 'jpyang' as valid output formats"""
        self.multiple_modules = True
        fmts['java'] = fmts['jpyang'] = self

    def add_opts(self, optparser):
        """Adds the --jpyang-help option"""
        optlist = [
            optparse.make_option(
                '-d', '--java-package',
                dest='directory',
                help='Generate output to DIRECTORY.'),
            optparse.make_option(
                '--jpyang-help',
                dest='jpyang_help',
                action='store_true',
                help='Print help on java format/JPyang usage and exit'),
            optparse.make_option(
                '--jpyang-debug',
                dest='debug',
                action='store_true',
                help='Print debug messages. Redundant if verbose mode is on.'),
            optparse.make_option(
                '--jpyang-javadoc',
                dest='javadoc_directory',
                help='Generate javadoc to JAVADOC_DIRECTORY.'),
            optparse.make_option(
                '--jpyang-no-schema',
                dest='no_schema',
                action='store_true',
                help='Do not generate schema.'),
            optparse.make_option(
                '--jpyang-verbose',
                dest='verbose',
                action='store_true',
                help='Verbose mode: Print detailed debug messages.'),
            ]
        g = optparser.add_option_group('JPyang output specific options')
        g.add_options(optlist)
        (self.o, args) = optparser.parse_args()

    def setup_ctx(self, ctx):
        """Called after ctx has been set up in main module. Checks if the
        jpyang help option was supplied and if not, that the -d or
        --java-package was used.

        ctx -- Context object as defined in __init__.py

        """
        if ctx.opts.jpyang_help:
            print_help()
            sys.exit(0)
        if (ctx.opts.format in ['java', 'jpyang'] and
            ctx.opts.directory is None):
            print >> sys.stderr, 'ERROR: Option -d (or --java-package) is' \
                ' mandatory when using the JPyang plug-in/Java output format'
            sys.exit(1)  # Makes above message more visible than self.fatal()

    def setup_fmt(self, ctx):
        """Disables implicit errors for the Context"""
        ctx.implicit_errors = False

    def emit(self, ctx, modules, fd):
        """Deletes any previous files in the supplied directory, creates
        directory structure and generates Java code to it.

        ctx     -- Context used to get output directory
        modules -- A list of pyang Statements, should be nothing else than
                   module and/or submodule statements.
        fd      -- File descriptor ignored.

        """
        directory = ctx.opts.directory
        wd = os.getcwd()
        # Create directory
        d = directory.replace('.', '/')
        try:
            os.makedirs(d, 0777)
        except OSError as exc:
            if exc.errno == errno.EEXIST:
                pass  # The directory already exists
            else:
                raise
        try:
            os.chdir(d)
        except OSError as exc:
            if exc.errno == errno.ENOTDIR:
                if ctx.opts.debug or ctx.opts.verbose:
                    print 'WARNING: Unable to change directory to ' + d + \
                        '. Probably a non-directory file with same name' + \
                        'as one of the subdirectories already exists.'
            else:
                raise
        if ctx.opts.debug or ctx.opts.verbose:
            print 'GENERATING FILES TO: ' + os.getcwd()
        for module in modules:
            if module.keyword == 'module' or module.keyword == 'submodule':
                if not ctx.opts.no_schema:
                    # Generate schema
                    ns = module.search_one('namespace').arg
                    name = module.search_one('prefix').arg.capitalize()
                    with open(os.getcwd() + '/' + name + '.schema', 'w+') as f:
                        f.write('<schema>\n' + indent( \
                            ('<node>\n' + \
                                indent(schema_node(module, '/', ns, ctx)) + \
                                '\n</node>' + \
                                schema_nodes(module.substmts, '/', ns, ctx) \
                            ).splitlines()) + '\n</schema>'
                    )
                    if ctx.opts.debug or ctx.opts.verbose:
                        print 'Schema generation COMPLETE.'
                # Generate Java classes
                src = 'module "' + module.arg + '", revision: "' + \
                    util.get_latest_revision(module) + '".'
                generate_classes(module, os.getcwd(), directory, src, ctx)
                if module.keyword == 'submodule':
                    # FIXME add support for submodule
                    print >> sys.stderr, \
                        'Warning: no support for submodule'
                if ctx.opts.debug or ctx.opts.verbose:
                    print 'Java classes generation COMPLETE.'
            else:
                print >> sys.stderr, \
                    'Error: unrecognized keyword: ' + module.keyword + \
                    'top-level element should be module or submodule'
                self.fatal()
        # Generate javadoc
        is_java_file = lambda s: s.endswith('.java')
        directory_listing = os.listdir(os.getcwd())
        java_files = filter(is_java_file, directory_listing)
        class_hierarchy = generate_javadoc(modules, java_files, ctx)
        gen_package(class_hierarchy, directory, ctx)
        os.chdir(wd)
        javadir = ctx.opts.javadoc_directory
        if javadir:
            if ctx.opts.debug or ctx.opts.verbose:
                print 'Generating javadoc...'
            if ctx.opts.verbose:
                os.system('javadoc -d ' + javadir + ' ' + d + '/*.java')
            else:
                os.system('javadoc -d ' + javadir + ' ' + d + \
                    '/*.java > /tmp/javadoc')
            if ctx.opts.debug or ctx.opts.verbose:
                print 'Javadoc generation COMPLETE.'

    def fatal(self, exitCode=1):
        """Raise an EmitError"""
        raise error.EmitError(self, exitCode)


def print_help():
    """Prints a description of what JPyang is and how to use it"""
    print '''
The JPyang/Java output format can be used to generate a Java class hierarchy
from a single yang data model. Each module, container, list, etc. is
represented by a .java file which can be used to retrieve and/or edit
configurations (e.g. by calling methods to add, delete or replace statements).

One way to use the Java output format plug-in of pyang is to type
$ pyang -f java -d output.package.dir <file.yang>

The two formats java and jpyang produce identical results.

Type '$ pyang --help' for more details on how to use pyang.
'''


def extract_keys(stmt, ctx):
    """Returns the key statement of stmt and lists containing tuples with the
    confm (and primitive, respectively) type of the key and its identifier.

    stmt -- Typically a list statement
    ctx  -- Context used for passing debug flags

    """
    key = stmt.search_one('key')
    confm_keys = []
    primitive_keys = []
    only_strings = True
    for arg in key.arg.split(' '):
        key_type = stmt.search_one('leaf', arg).search_one('type')
        if key_type.arg == 'string':
            confm_keys.append(('com.tailf.confm.xs.String', arg))
            primitive_keys.append(('String', arg))
        elif key_type.arg == 'uint32':
            confm_keys.append(('com.tailf.confm.xs.UnsignedInt', arg))
            primitive_keys.append(('long', arg))
        else:
            if ctx.opts.debug or ctx.opts.verbose:
                print >> sys.stderr, 'WARNING! No support for type "' + \
                key_type.arg + '", defaulting to string.'
            confm_keys.append(('com.tailf.confm.xs.String', arg))
            primitive_keys.append(('String', arg))
        only_strings *= primitive_keys[-1][0] == 'String'
    return key, only_strings, confm_keys, primitive_keys


def extract_names(arg):
    """Returns a tuple with arg capitalized and prepended with .java, and arg
    capitalized.

    arg -- Any string, really

    """
    capitalized = arg.capitalize()
    return (capitalized + '.java', capitalized)


def is_module(stmt):
    """Returns True iff stmt is a module or submodule."""
    return stmt.keyword == 'module' or stmt.keyword == 'submodule'


def is_container(stmt, strict=False):
    """Returns True iff stmt is a list, container or something of the sort."""
    return (stmt.keyword == 'container' or
        (not strict and stmt.keyword == 'list'))


def in_schema(stmt):
    """Returns True iff stmt is to be included in schema."""
    return (is_container(stmt) or
        stmt.keyword == 'module' or
        stmt.keyword == 'leaf')


def indent(lines, level=1):
    """Returns a string consisting of all strings in lines concatenated,
    each string prepended by a level*4 number of spaces and appended with
    a newline, except the last which has no newline.

    lines -- list of strings
    level -- indentation level (number of spaces divided by 4)

    """
    # TODO implement a more efficient version using replace on strings
    res = ''
    for line in lines:
        res += ' ' * level * 4 + line + '\n'
    return res[:-1]  # Don't include the last newline character


def java_docify(s):
    """Returns the string s, but with each row prepended by ' * '"""
    res = ''
    for row in s.splitlines():
        res += ' * ' + row + '\n'
    return res[:-1]  # Don't include the last newline character


def schema_nodes(stmts, tagpath, ns, ctx):
    """Generate XML schema as a list of "node" elements"""
    res = ''
    for stmt in stmts:
        if in_schema(stmt):
            res += '<node>\n' + \
                indent(schema_node(stmt, tagpath + stmt.arg + '/', ns,
                    ctx)) + '\n</node>' + schema_nodes(stmt.substmts,
                    tagpath + stmt.arg + '/', ns, ctx)
    return res


def schema_node(stmt, tagpath, ns, ctx):
    """Generate "node" element content for an XML schema"""
    if ctx.opts.verbose:
        print 'Generating schema node "' + tagpath + '"...'
    res = []
    res.append('<tagpath>' + tagpath + '</tagpath>')  # or stmt.full_path()
    # ... but it is marked for removal (and it would be less efficient)
    res.append('<namespace>' + ns + '</namespace>')
    res.append('<primitive_type></primitive_type>')

    min_occurs = '0'
    max_occurs = '-1'
    mandatory = stmt.search_one('mandatory')
    isMandatory = mandatory is not None and mandatory.arg == 'true'
    unique = stmt.search_one('unique')
    isUnique = unique is not None and unique.arg == 'true'
    key = None
    if stmt.parent is not None:
        key = stmt.parent.search_one('key')
    isKey = key is not None and key.arg == stmt.arg
    childOfContainerOrList = (stmt.parent is not None and \
        is_container(stmt.parent))
    if (is_module(stmt) or isKey or
        (childOfContainerOrList and is_container(stmt, True))):
        min_occurs = '1'
        max_occurs = '1'
    if isMandatory:
        min_occurs = '1'
    if isUnique or childOfContainerOrList or is_container(stmt, True):
        max_occurs = '1'
    res.append('<min_occurs>' + min_occurs + '</min_occurs>')  # TODO correct?
    res.append('<max_occurs>' + max_occurs + '</max_occurs>')  # TODO correct?

    children = ''
    for ch in stmt.substmts:
        children += ch.arg + ' '
    res.append('<children>' + children[:-1] + '</children>')

    res.append('<flags></flags>')
    res.append('<desc></desc>')
    return res


def generate_classes(module, directory, package, src, ctx):
    """Generates a Java class hierarchy providing an interface to a YANG module

    module    -- A data model tree, parsed from a YANG model
    directory -- Path to where files should be written
    package   -- Name of Java package
    src       -- The .yang file from which the module was parsed, or the module
                 name and revision if filename is unknown
    ctx       -- Context used to fetch option parameters

    """
    if module.keyword == 'module':
        ns_arg = module.search_one('namespace').arg
        prefix = module.search_one('prefix')
    elif module.keyword == 'submodule':
        parent_module = module.search_one('belongs-to')
        prefix = parent_module.search_one('prefix')
        ns_arg = '<unknown/prefix: ' + prefix.arg + '>'
    (filename, name) = extract_names(prefix.arg)
    for stmt in module.substmts:
        if (stmt.keyword == 'container' or
            stmt.keyword == 'list'):  # FIXME add support for submodule, etc.
            generate_class(stmt, directory, package, src, '', ns_arg, name,
                top_level=True, ctx=ctx)
    if ctx.opts.verbose:
        print 'Generating Java class "' + filename + '"...'
    with open(directory + '/' + filename, 'w + ') as f:
        f.write(java_class(filename, package,
            ['com.tailf.confm.*', 'com.tailf.inm.*', 'java.util.Hashtable'],
            'The root class for namespace ' + ns_arg + \
            ' (accessible from \n * ' + name + '.NAMESPACE) with prefix "' + \
            prefix.arg + '" (' + name + '.PREFIX).',
            class_fields(ns_arg, prefix.arg) +
            enable(name) + register_schema(name),
            source=src
        )
    )


def generate_class(stmt, directory, package, src, path, ns, prefix_name, ctx,
        top_level=False):
    """Generates a Java class hierarchy providing an interface to a YANG module

    stmt        -- A data model subtree
    directory   -- Path to where files should be written
    package     -- Name of Java package
    src         -- The .yang file from which the module was parsed, or the
                   module name and revision if filename is unknown
    path        -- The XPath of stmt in the original module
    ns          -- The XML namespace of the module
    prefix_name -- The module prefix
    top_level   -- Whether or not this is a top-level statement
    ctx         -- Context used to fetch option parameters

    """
    (filename, name) = extract_names(stmt.arg)
    access_methods = constructors = cloners = support_methods = ''
    fields = []
    for sub in stmt.substmts:
    # FIXME Perhaps better to have several loops to get correct order and be
    #      able to call generate_class outside of if-statements
        if sub.keyword == 'list':
            generate_class(sub, directory, package, src, path + stmt.arg + '/',
                ns, prefix_name, ctx)
            key, _, confm_keys, _ = extract_keys(sub, ctx)
            access_methods += access_methods_comment(sub) + \
            get_stmt(sub, confm_keys) + \
            get_stmt(sub, confm_keys, string=True) + \
            child_iterator(sub) + \
            add_stmt(sub, args=[(sub.arg, sub.arg)]) + \
            add_stmt(sub, args=confm_keys) + \
            add_stmt(sub, args=confm_keys, string=True) + \
            add_stmt(sub, args=[]) + \
            delete_stmt(sub, args=confm_keys) + \
            delete_stmt(sub, args=confm_keys, string=True)
        elif sub.keyword == 'container':
            generate_class(sub, directory, package, src, path + stmt.arg + '/',
                ns, prefix_name, ctx)
            fields.append(sub.arg)  # FIXME might have to append more fields
            access_methods += access_methods_comment(sub) + \
            child_field(sub) + \
            add_stmt(sub, args=[(sub.arg, sub.arg)], field=True) + \
            add_stmt(sub, args=[], field=True) + \
            delete_stmt(sub)
        elif sub.keyword == 'leaf':
            key = stmt.search_one('key')
            if key is not None and sub.arg in key.arg.split(' '):
                temp = statements.Statement(None, None, None, 'key',
                    arg=sub.arg)
                optional = False
                # Pass temp to avoid multiple keys
                access_methods += access_methods_comment(temp, optional)
            else:
                optional = True
                access_methods += access_methods_comment(sub, optional)
                #TODO ensure that the leaf is really optional
            type_stmt = sub.search_one('type')
            if type_stmt.arg == 'uint32':
                type_str = 'com.tailf.confm.xs.UnsignedInt'
                access_methods += get_value(sub, ret_type=type_str) + \
                    set_value(sub, prefix=prefix_name, arg_type=type_str) + \
                    set_value(sub, prefix='', arg_type='String',
                        confm_type=type_str) + \
                    set_value(sub, prefix='', arg_type='long',
                        confm_type=type_str)
            elif type_stmt.arg == 'string':
                type_str = 'com.tailf.confm.xs.String'
                access_methods += get_value(sub, ret_type=type_str) + \
                    set_value(sub, prefix=prefix_name, arg_type=type_str) + \
                    set_value(sub, prefix='', arg_type='String',
                        confm_type=type_str)
            else:
                if ctx.opts.debug or ctx.opts.verbose:
                    print >> sys.stderr, 'WARNING! No support for type "' + \
                        type_stmt.arg + '", defaulting to string.'
                    type_str = 'com.tailf.confm.xs.String'
                access_methods += get_value(sub, ret_type=type_str) + \
                    set_value(sub, prefix=prefix_name, arg_type=type_str) + \
                    set_value(sub, prefix='')
            if optional:
                access_methods += unset_value(sub)
            access_methods += add_value(sub, prefix_name)
            if optional:
                access_methods += mark(sub, 'replace') + \
                mark(sub, 'merge') + \
                mark(sub, 'create') + \
                mark(sub, 'delete')
        elif sub.keyword == 'leaf-list':
            type_stmt = sub.search_one('type')
            access_methods += access_methods_comment(sub, optional=False) + \
                child_iterator(sub)
            if type_stmt.arg == 'uint32':
                type_str = 'com.tailf.confm.xs.UnsignedInt'
                access_methods += set_value(sub, prefix=prefix_name,
                    arg_type=type_str) + \
                    set_value(sub, prefix='', arg_type='String',
                        confm_type=type_str) + \
                    set_value(sub, prefix='', arg_type='long',
                        confm_type=type_str)
            elif type_stmt.arg == 'string':
                type_str = 'com.tailf.confm.xs.String'
                access_methods += set_value(sub, prefix=prefix_name,
                    arg_type=type_str) + \
                    set_value(sub, prefix='', arg_type='String',
                        confm_type=type_str)
            else:
                if ctx.opts.debug or ctx.opts.verbose:
                    print >> sys.stderr, 'WARNING! No support for type "' + \
                        type_stmt.arg + '", defaulting to string.'
                    type_str = 'com.tailf.confm.xs.String'
                access_methods += set_value(sub, prefix=prefix_name,
                    arg_type=type_str) + \
                    set_value(sub, prefix='', arg_type='String',
                        confm_type=type_str)
            access_methods += delete_stmt(sub,
                    args=[(type_str, sub.arg + 'Value')], keys=False) + \
                delete_stmt(sub, args=[(type_str, sub.arg + 'Value')],
                    string=True, keys=False) + \
                add_value(sub, prefix_name) + \
                mark(sub, 'replace', arg_type=type_str) + \
                mark(sub, 'replace', arg_type='String') + \
                mark(sub, 'merge', arg_type=type_str) + \
                mark(sub, 'merge', arg_type='String') + \
                mark(sub, 'create', arg_type=type_str) + \
                mark(sub, 'create', arg_type='String') + \
                mark(sub, 'delete', arg_type=type_str) + \
                mark(sub, 'delete', arg_type='String')
        elif sub.keyword == 'uses':
            print 'USES..... ' + sub.arg
        elif sub.keyword == 'grouping':
            print 'Grouping: ' + sub.arg
        else:
            print sub.keyword + ': ' + sub.arg
    if ctx.opts.verbose:
        print 'Generating Java class "' + filename + '"...'
    if filter(is_container, stmt.substmts):  # TODO Verify correctness of cond.
        support_methods = support_add(fields)
    if stmt.keyword == 'container':
        constructors = constructor(stmt, ctx, set_prefix=top_level,
            root=prefix_name)
        cloners = clone(name, shallow=False) + clone(name, shallow=True)
    elif stmt.keyword == 'list':
        key, only_strings, confm_keys, primitive_keys = extract_keys(stmt, ctx)
        constructors = constructor(stmt, ctx, root=prefix_name,
            set_prefix=top_level, throws="\n        throws INMException") + \
        constructor(stmt, ctx, root=prefix_name, set_prefix=top_level,
            mode=1, args=confm_keys, throws='''
        throws INMException''') + \
        constructor(stmt, ctx, root=prefix_name, set_prefix=top_level,
            mode=2, args=primitive_keys, throws='''
        throws INMException''')
        if not only_strings:
            constructors += constructor(stmt, ctx, root=prefix_name,
                set_prefix=top_level, mode=3, args=primitive_keys, throws='''
        throws INMException''')
        cloners = clone(name, map(str.capitalize, key.arg.split(' ')),
            shallow=False) + \
            clone(name, map(str.capitalize, key.arg.split(' ')), shallow=True)
    with open(directory + '/' + filename, 'w + ') as f:
        f.write(java_class(filename, package,
            ['com.tailf.confm.*', 'com.tailf.inm.*', 'java.util.Hashtable'],
            # FIXME Hashtable not used in generated code
            'This class represents a "' + path + stmt.arg +
            '" element\n * from the namespace ' + ns,
            constructors + cloners + key_names(stmt) +
            children_names(stmt) + access_methods + support_methods,
            # TODO add getters, setters, etc. for children stmts
            source=src,
            modifiers=' extends Container'
        )
    )


def generate_javadoc(stmts, java_files, ctx):
    """Generates a list of class filenames and lists of their subclasses'
    filenames, positioned immediately after each filename if any.

    stmts      -- list of statements representing a YANG module tree node
    java_files -- list of Java class filenames that has been generated
    ctx        -- Context, ignored

    """
    hierarchy = []
    for stmt in stmts:
        (filename, name) = extract_names(stmt.arg)
        if filename in java_files:
            java_files.remove(filename)
            hierarchy.append(filename)
            children = generate_javadoc(stmt.substmts, java_files, ctx)
            if children:
                hierarchy.append(children)
    return hierarchy


def java_class(filename, package, imports, description, body, version='1.0',
               modifiers='', source='<unknown>.yang'):
    """The java_class function returns a string representing Java code for a
    class.

    filename    -- Should preferably not contain a complete path since it is
                   displayed in a Java comment in the beginning of the code.
    package     -- Should be just the name of the package in which the class
                   will be included.
    imports     -- Should be a list of names of imported libraries.
    description -- Defines the class semantics.
    body        -- Should contain the actual code of the class
    version     -- Version number, defaults to '1.0'.
    modifiers   -- Can contain Java statements
                   such as ' implements Serializable' or ' extends Element'.
    source      -- A string somehow representing the origin of the class

    """
    # Fetch current date and set date format
    time = datetime.date.today()
    date = str(time.day) + '/' + str(time.month) + '/' + str(time.year % 100)
    # The header_comment is placed in the beginning of the Java file
    header_comment = '/* \n * @(#)' + filename + ' ' * 8 + version + ' ' + \
        date + '''
 *
 * This file has been auto-generated by JPyang, the Java output format plug-in
 * of pyang. Origin: ''' + source + '\n */'
    # Change date format for class doc comment
    date = str(time.year) + '-' + str(time.month) + '-' + str(time.day)
    class_doc = '''/**
 * ''' + description + '''
 *
 * @version    ''' + version + ' ' + date + '''
 * @author    Auto Generated
 */'''
    # package and import statement goes here
    header = header_comment + '\n\npackage ' + package + ';\n'
    if len(imports) > 0:
        header += '\n'
    for im in imports:
        header += 'import ' + im + ';\n'
    header += '\n' + class_doc + '\n'
    # Here is the class declaration, with modifiers.
    # The class name is the filename without the file extension.
    class_decl = 'public class ' + filename.split('.')[0] + modifiers + ' {\n'
    return header + class_decl + body + '\n}'


def constructor(stmt, ctx, root='', set_prefix=False, mode=0, args=[],
    throws=''):
    """The constructor function returns a string representing Java code for a
    constructor of a Java class corresponding to the stmt parameter.

    stmt        -- Typically a module, submodule, container or list Statement
    ctx         -- Context used to identify debug and verbose flags
    root        -- Path to class containing the XML namespace prefix of the
                   YANG module. If not set stmt name will be used.
    set_prefix  -- Set to true to add setDefaultPrefix and setPrefix calls
    mode        -- 0: No arguments
                   1: ConfM arguments
                   2: String arguments
                   3: Java primitive arguments
    args        -- A list of tuples containing the argument type(s) and
                   name(s). If empty, the method will have no argument. The
                   argument name(s) should be supplied without the 'Value'
                   suffix. Typically used as a (set of) key(s) in the method.
                   Note that mode must be > 0 for this to have an effect.
    throws      -- Typically 'throws INMException', prepended with a newline
                   and spaces for indentation.

    """
    name = stmt.arg.capitalize()
    setters = docstring = inserts = arguments = ''
    MAX_COLS = 80 - len('    public ' + name + '(')
    if root == '':
        root = name
    if set_prefix:
        setters = '''
        setDefaultPrefix();
        setPrefix(''' + root + '.PREFIX);'
    if not args or mode == 0:
        obj_status = 'empty '
    else:
        obj_status = 'initialized '
        values = []
        if mode == 1:  # ConfM arguments
            for (arg_type, arg_name) in args:
                values.append(arg_name + 'Value')
        else:  # String or Java primitive arguments
            if mode == 2:
                docstring = '\n     * with Strings for the keys.'
            else:
                docstring = '\n     * with primitive Java types.'
            for (arg_type, arg_name) in args:
                if arg_type == 'String':
                    decl = 'new com.tailf.confm.xs.String('
                elif arg_type == 'long':
                    decl = 'new com.tailf.confm.xs.UnsignedInt('
                else:
                    # FIXME support more types!
                    if ctx.opts.debug or ctx.opts.verbose:
                        print >> sys.stderr, 'WARNING, at line ' + \
                            str(currentframe().f_lineno) + \
                            ' constructor argument' + \
                            ' defaulting to string from: ' + arg_type
                    decl = 'new com.tailf.confm.xs.String('
                values.append(decl + arg_name + 'Value)')
        for (arg_type, arg_name), value in zip(args, values):
            inserts += '''
        // Set key element: ''' + arg_name + '''
        Leaf ''' + arg_name + ' = new Leaf(' + root + '.NAMESPACE, "' + \
            arg_name + '''");
        ''' + arg_name + '.setValue(' + value + ''');
        insertChild(''' + arg_name + ', childrenNames());'  # FIXME throws
            arg_name = arg_name + 'Value'
            docstring += '\n     * @param ' + arg_name + \
                ' Key argument of child.'
            if mode == 2:  # String arguments
                tmp = 'String ' + arg_name + ', '
            else:  # ConfM or Java primitive arguments
                tmp = arg_type + ' ' + arg_name + ', '
            if len(tmp) > MAX_COLS:
                tmp = '\n' + ' ' * 8 + tmp
                MAX_COLS = 80 - len(tmp)
            else:
                MAX_COLS -= len(tmp)
            arguments += tmp
        arguments = arguments[:-2]  # Skip the last ', '
    return '''
    /**
     * Constructor for an ''' + obj_status + name + ' object.' + docstring + \
     '''
     */
    public ''' + name + '(' + arguments + ')' + throws + ''' {
        super(''' + root + '.NAMESPACE, "' + stmt.arg + '");' + \
        inserts + setters + '''
    }
'''


def clone(class_name, key_names=[], shallow='False'):
    """Returns a string representing a Java clone method. Iff key_names is
    empty, get<key_name>Value() methods are called to fetch constructor
    arguments and null is returned if an INMException is raised. If shallow is
    set, the cloneShallowContent method is invoked instead of cloneContent.

    class_name -- The name of the class to clone instances of
    key_names  -- Key identifier(s)
    shallow    -- Boolean flag for which clone method to use

    """
    try_stmt = children = cast = ''
    if key_names:
        try_stmt = 'try {\n' + ' ' * 12
        catch_stmt = '('
        MAX_COLS = 80 - 44 - len(class_name)
        for key_name in key_names:
            tmp = 'get' + key_name + 'Value(), '
            if len(tmp) > MAX_COLS:
                tmp = '\n' + ' ' * 16 + tmp
                MAX_COLS = 80 - len(tmp)
            else:
                MAX_COLS -= len(tmp)
            catch_stmt += tmp
        catch_stmt = catch_stmt[:-2] + '''));
        } catch (INMException e) { return null; }
    }\n'''
    else:
        catch_stmt = '());\n    }\n'
    if not shallow:
        copy = 'n exact'
        signature = 'Object clone()'
        cast = '(' + class_name + ')'  # FIXME Maybe not always required
        method = 'cloneContent'
    else:
        copy = ' shallow'
        children = ' Children are not included.'
        signature = 'Element cloneShallow()'
        method = 'cloneShallowContent'
    return '''
    /**
     * Clones this object, returning a''' + copy + ''' copy.
     * @return A clone of the object.''' + children + '''
     */
    public ''' + signature + ''' {
        ''' + try_stmt + 'return ' + cast + method + '(new ' + class_name + \
            catch_stmt


def key_names(stmt):
    """Returns a string representing a Java method that returns a String[]
    with the identifiers of the keys in stmt. If stmt does not have any keys,
    null is returned.

    stmt -- A pyang Statement, typically a list or a container

    """
    keys = stmt.search('key')
    if not keys:
        res = 'return null'
    else:
        res = 'return new String[] {\n'
        # Add keys to res, one key per line, indented by 12 spaces
        for key_str in keys:
            for key in key_str.arg.split(' '):
                res += ' ' * 12 + '"' + key + '",\n'
        res = res[:-2] + '\n' + ' ' * 8 + '}'
    return '''
    /**
     * Structure information which specifies
     * the keys for the list entries.
     */
    public String[] keyNames() {
        ''' + res + ''';
    }
'''  # FIXME Add support for multiple keys


def children_names(stmt):
    """Returns a string representing a java method that returns a String[]
    with the identifiers of the children of stmt, excluding any keys.

    stmt -- A pyang Statement, typically a list or a container

    """
    children = filter(lambda x:  # x.keyword != 'key' and # FIXME add more
        x.keyword != 'key',
        stmt.substmts)
    names = [ch.arg for ch in children]
    if len(names) > 0:
        names = repr(names)[1:-1].replace("'", '"').replace(', ',
            ',\n' + ' ' * 12)
    else:
        names = ''
    return '''
    /**
     * Structure information with the names of the children.
     * Makes it possible to order the children.
     */
    public String[] childrenNames() {
        return new String[] {
            ''' + names + '''
        };
    }
'''  # FIXME What if there are no children?


def class_fields(ns_arg, prefix_arg):
    """Returns a string representing java code for two fields"""
    return '''
    public static final String NAMESPACE = "''' + ns_arg + '''";

    public static final String PREFIX = "''' + prefix_arg + '''";
    '''


def enable(prefix_name):
    """Returns a string representing a java method that calls the
    Container.setPackage method of the confm library, and the registerSchema
    method of the class with prefix == prefix_name (typically = this).

    prefix_name -- The name of the class containing the registerSchema method

    """
    return '''
    /**
     * Enable the elements in this namespace to be aware
     * of the data model and use the generated classes.
     */
    public static void enable() throws INMException {
        Container.setPackage(NAMESPACE, PREFIX);
        ''' + prefix_name + '''.registerSchema();
    }
'''


def register_schema(prefix_name):
    """Returns a string representing a java method that creates a SchemaParser
    and calls its readFile method with the schema corresponding to the class
    and a hashtable obtained from a call to CsTree.create (a method in the
    ConfM library).

    prefix_name -- The name of the class containing the registerSchema method

    """
    return '''
    /**
     * Register the schema for this namespace in the global
     * schema table (CsTree) making it possible to lookup
     * CsNode entries for all tagpaths
     */
    public static void registerSchema() throws INMException {
        StackTraceElement[] sTrace = (new Exception()).getStackTrace();
        ClassLoader loader = sTrace[0].getClass().getClassLoader();
        java.net.URL schemaUrl = loader.getSystemResource("''' + \
            prefix_name + '''.schema");
        SchemaParser parser = new SchemaParser();
        Hashtable h = CsTree.create(NAMESPACE);
        if (schemaUrl == null)
            parser.readFile("''' + prefix_name + '''.schema", h);
        else
            parser.readFile(schemaUrl, h);
    }
'''


def access_methods_comment(stmt, optional=False):
    """Returns a string representing a java comment for code structure"""
    if optional:
        opt = 'optional '
    else:
        opt = ''
    return '''
    /**
     * -------------------------------------------------------
     * Access methods for ''' + opt + stmt.keyword + \
     ' child: "' + stmt.arg + '''".
     * -------------------------------------------------------
     */
'''


def child_field(stmt):
    """Returns a string representing java code for a field"""
    return '''
    /**
     * Field for child ''' + stmt.keyword + ' "' + stmt.arg + '''".
     */
    public ''' + stmt.arg.capitalize() + ' ' + stmt.arg + ''' = null;
'''


def get_stmt(stmt, keys, string=False):
    """Get method generator. Similar to add_stmt (see below), but does not
    allow parameter-free methods to be generated.

    stmt   -- Typically a list statement
    keys   -- A list of key types and the corresponding identifiers
    string -- if set to True, keys are specified as Strings in method

    """
    name = stmt.arg.capitalize()
    spec = arguments = xpath = ''
    if string:
        spec = '\n     * The keys are specified as Strings'
    for (key_type, key_name) in keys:
        spec += '\n     * @param ' + key_name + ' Key argument of child.'
        if string:  # TODO http://en.wikipedia.org/wiki/Loop_unswitching
            arguments += 'String ' + key_name + ', '
        else:
            arguments += key_type + ' ' + key_name + ', '
        xpath += '[' + key_name + '=\'" + ' + key_name + ' + "\']'
    return '''
    /**
     * Get method for ''' + stmt.keyword + ' entry: "' + stmt.arg + '''".
     * Return the child with the specified keys ''' + \
     '(if any).' + spec + '''
     * @return The ''' + stmt.keyword + ''' entry with the specified keys.
     */
    public ''' + name + ' get' + name + '(' + arguments[:-2] + ''')
        throws INMException {
        String path = "''' + stmt.arg + xpath + '''";
        return (''' + name + ''')getListContainer(path);
    }
'''


def get_value(stmt, ret_type='com.tailf.confm.xs.String'):
    """get<Identifier>Value method generator. Similar to get_stmt (see below),
    but allows parameter-free methods to be generated.

    stmt     -- Typically a leaf statement
    ret_type -- The type of the return value of the generated method

    """
    name = stmt.arg.capitalize()
    return '''
    /**
     * Return the value for child ''' + stmt.keyword + ' "' + stmt.arg + '''".
     * @return The value of the ''' + stmt.keyword + '''.
     */
    public ''' + ret_type + ' get' + name + '''Value()
        throws INMException {
        return (''' + ret_type + ')getValue("' + stmt.arg + '''");
    }
'''


def set_value(stmt, prefix='', arg_type='', confm_type=''):
    """set<Identifier>Value method generator.

    stmt       -- Typically a leaf statement
    prefix     -- Namespace prefix of module, empty if the setLeafValue method
                  is not to be used in the method
    arg_type   -- Type of method parameter, empty if parameter free
    confm_type -- Type to use internally, empty if the setIdValue method is not
                  to be used in the method

    """
    name = stmt.arg.capitalize()
    spec1 = spec2 = ''
    MAX_COLS = 80 - len('     * Sets the value for child ' + stmt.keyword + \
        ' "' + stmt.arg + '",.')  # Space left to margin
    if arg_type == 'String':
        spec1 = ', using a string value'
        spec2 = 'string representation of the '
    elif arg_type == 'long':
        spec1 = ', using the java primitive value'
    print('set' + name + 'Value(' + arg_type + ' ' + stmt.arg + \
        'Value): \nlen(spec1)=' + \
        str(len(spec1)) + ' MAX_COLS=' + str(MAX_COLS))
    if len(spec1) > MAX_COLS:
        spec1 = ',\n     * ' + spec1[2:]
    if prefix:
        if stmt.keyword == 'leaf-list':
            body = 'setLeafListValue('
        else:
            body = 'setLeafValue('
        body += prefix + '''.NAMESPACE,
            "''' + stmt.arg + '''",
            ''' + stmt.arg + '''Value,
            childrenNames());'''
    else:
        body = 'set' + name + 'Value(new ' + confm_type + '(' + stmt.arg + \
            'Value));'
    return '''
    /**
     * Sets the value for child ''' + stmt.keyword + ' "' + stmt.arg + '"' + \
        spec1 + '''.
     * @param ''' + stmt.arg + 'Value The ' + spec2 + '''value to set.
     */
    public void set''' + name + 'Value(' + arg_type + ' ' + stmt.arg + \
        '''Value)
        throws INMException {
        ''' + body + '''
    }
'''


def unset_value(stmt):
    """unset<Identifier> method generator"""
    return '''
    /**
     * Unsets the value for child ''' + stmt.keyword + ' "' + stmt.arg + '''".
     */
    public void unset''' + stmt.arg.capitalize() + '''Value()
        throws INMException {
        delete("''' + stmt.arg + '''");
    }
'''


def add_value(stmt, prefix):
    """add<Identifier> method generator, designed for leaf statements. Not to
    be confused with the add_stmt function which is similar but does not
    contain a call to the setLeafValue function.

    stmt   -- Typically a leaf statement
    prefix -- Namespace prefix of module

    """
    name = value_type = ''
    if stmt.keyword == 'leaf-list':
        name = 'Empty'
        value_type = 'List'
    name += stmt.arg.capitalize()
    return '''
    /**
     * This method is used for creating a subtree filter.
     * The added "''' + stmt.arg + '" ' + stmt.keyword + \
        ''' will not have a value.
     */
    public void add''' + name + '''()
        throws INMException {
        setLeaf''' + value_type + 'Value(' + prefix + '''.NAMESPACE,
            "''' + stmt.arg + '''",
            null,
            childrenNames());
    }
'''


def mark(stmt, op, arg_type='String'):
    """Generates a method that enqueues an operation to be performed on an
    element.

    stmt     -- Typically a leaf or leaf-list statement. If stmt is not a leaf-
                list, the method will have no argument.
    op       -- The operation 'replace', 'merge', 'create' or 'delete'
    arg_type -- Type of argument, if any.

    """
    spec = op + '"'
    path = stmt.arg
    argument = ''
    if stmt.keyword == 'leaf-list':
        spec += '''.
     * @param ''' + stmt.arg + 'Value The value to mark'
        if arg_type == 'String':
            spec += ', given as a String'
        argument = arg_type + ' ' + stmt.arg + 'Value'
        path += '[name=\'" + ' + stmt.arg + 'Value+"\']'
    return '''
    /**
     * Marks the "''' + stmt.arg + '" ' + stmt.keyword + \
        ' with operation "' + spec + '''.
     */
    public void mark''' + stmt.arg.capitalize() + op.capitalize() + '(' + \
        argument + ''')
        throws INMException {
        markLeaf''' + op.capitalize() + '("' + path + '''");
    }
'''


def child_iterator(substmt):
    """Returns a string representing a java iterator method for the substmt"""
    if substmt.keyword == 'leaf-list':
        iterator_type = 'LeafListValue'
    else:
        iterator_type = 'Children'
    return '''
    /**
     * Iterator method for the ''' + substmt.keyword + ' "' + substmt.arg + \
        '''".
     * @return An iterator for the ''' + substmt.keyword + '''.
     */
    public Element''' + iterator_type + 'Iterator ' + substmt.arg + \
        '''Iterator() {
        return new Element''' + iterator_type + 'Iterator(children, "' + \
        substmt.arg + '''");
    }
'''


def add_stmt(stmt, args=[], field=False, string=False):
    """Generates add-method for stmt, optionally parametrized by an
    argument of specified type and with customizable comments.

    stmt   -- The YANG statement that needs an adder
    args   -- A list of tuples, each tuple containing an arg_type and an
              arg_name. Each arg_type corresponds to a method argument type
              which is also used to deduce what the method should do:
              1. If arg_type is the same as stmt.arg, the produced method
                 will add its argument as a child instead of creating a new
                 one. No cloning occurs.
              2. Tail-f ConfM types produces a method that adds a new stmt
                 with that key of the Tail-f String type, unless string is set.
              Each arg_name corresponds to a method argument name. The names of
              the method's arguments are typically key identifiers or a single
              lowercase stmt name. Setting args to an empty list produces a
              method with no argument, which can be used to create subtree
              filters.
    string -- If set to True, the keys are specified with the ordinary String
              type instead of the Tail-f ConfM String type.
    field  -- If set to True, the statement is added to a field, typically
              in a container class.

    """
    name = stmt.arg.capitalize()
    spec2 = spec3 = ''
    if len(args) == 1 and args[0][0] == stmt.arg:
        spec1 = '.\n     * @param ' + args[0][1] + \
            ' Child to be added to children'
        spec2 = name + ' ' + stmt.arg + ', '
    else:
        spec3 = '\n' + ' ' * 8 + name + ' ' + stmt.arg + \
            ' = new ' + name + '('
        if not args:
            spec1 = '''.
     * This method is used for creating subtree filters'''
            spec3 += ');'
        else:
            spec1 = ', with given key arguments'
            if string:
                spec1 += '.\n     * The keys are specified as strings'
            for (arg_type, arg_name) in args:
                spec1 += '.\n     * @param ' + arg_name + \
                    ' Key argument of child'
                if string:
                    spec2 += 'String ' + arg_name + ', '
                else:
                    spec2 += arg_type + ' ' + arg_name + ', '
                spec3 += arg_name + ', '
            spec3 = spec3[:-2] + ');'
    if field:
        spec3 += '\n' + ' ' * 8 + 'this.' + stmt.arg + ' = ' + stmt.arg + ';'
    return '''
    /**
     * Adds ''' + stmt.keyword + ' entry "' + stmt.arg + '"' + spec1 + '''.
     * @return The added child.
     */
    public ''' + name + ' add' + name + '(' + spec2[:-2] + ''')
        throws INMException {''' + spec3 + '''
        insertChild(''' + stmt.arg + ''', childrenNames());
        return ''' + stmt.arg + ''';
    }
'''


def delete_stmt(stmt, args=[], string=False, keys=True):
    """Delete method generator. Similar to add_stmt (see above).

    stmt   -- Typically a list or container statement
    args   -- A list of tuples, each tuple containing an arg_type and an
              arg_name. Each arg_type corresponds to a method argument type.
              Each arg_name corresponds to a method argument name. The names of
              the method's arguments are typically key identifiers or a single
              lowercase stmt name. Setting args to an empty list produces a
              method with no argument.
    string -- If set to True, the keys are specified with the ordinary String
              type instead of the Tail-f ConfM String type.

    """
    spec1 = spec2 = spec3 = arguments = ''
    if args:
        if keys:
            spec1 = '", with specified keys.'
            if string:
                spec1 += '\n     * The keys are specified as Strings'
        elif string:
            spec1 += '\n     * The value is specified as a String'
        for (arg_type, arg_name) in args:
            if string:
                arguments += 'String ' + arg_name + ', '
            else:
                arguments += arg_type + ' ' + arg_name + ', '
            if keys:
                spec1 += '\n     * @param ' + arg_name + \
                    ' Key argument of child.'
                spec3 += '[' + arg_name + '=\'" + ' + arg_name + ' + "\']'
            else:
                spec1 += '\n     * @param ' + arg_name + \
                    ' Child to be removed.'
                spec3 += '[name=\'" + ' + arg_name + ' + "\']'
    else:
        spec1 = ''
        spec2 = 'this.' + stmt.arg + ' = null;\n        '
    return '''
    /**
     * Deletes ''' + stmt.keyword + ' entry "' + stmt.arg + spec1 + '''"
     */
    public void delete''' + stmt.arg.capitalize() + '(' + arguments[:-2] + ''')
        throws INMException {
        ''' + spec2 + 'String path = "' + stmt.arg + spec3 + '''";
        delete(path);
    }
'''


def support_add(fields=[]):
    """Generates an addChild method.

    fields -- a list of fields in the generated class

    """
    assignments = ''
    for i in range(len(fields) - 1, -1, -1):
        assignments += 'if ($child instanceof ' + fields[i].capitalize() + \
            ') ' + fields[i] + ' = (' + fields[i].capitalize() + ')$child;'
        if i > 0:
            assignments += '\n        else '
    return '''
    /**
     * -------------------------------------------------------
     * Support method for addChild.
     * -------------------------------------------------------
     */

    /**
     * Adds a child to this object.
     */
    public void addChild(Element $child) {
        super.addChild($child);
        ''' + assignments + '''
    }
'''  # FIXME '$' should be removed unless it is actually needed


def is_not_list(entry):
    """Returns False iff entry is instance of list"""
    return not isinstance(entry, list)


def html_list(body, indent_level, tag='ul'):
    """Returns a string representing javadoc with a <ul> html-element if ul,
    else with a <li> html-element.

    """
    body = '<' + tag + '>\n' + body
    if body[-1:] != '\n':
        body += '\n'
    body += '</' + tag + '>'
    return indent(body.split('\n'), indent_level)


def parse_hierarchy(hierarchy):
    """Returns html for a list of javadoc pages corresponding to the .java
    files in the hierarchy list.

    hierarchy -- a tree of .java files represented as a list, for example:
        ['Foo.java', ['Bar.java', ['Baz.java'], 'Qu.java']] would represent the
        hierarchy structure:
        Foo
        |   Bar
        |   |   Baz
        |   Qu

        That is, Baz is a child of Bar in the data model tree, and Bar and Qu
        are children of the top level element Foo.

    """
    res = ''
    for entry in hierarchy:
        if is_not_list(entry):
            body = '    <a href="' + entry[:-5] + '.html">' + entry[:-5] + \
                '</a>'
            res += html_list(body, 1, tag='li')
        else:
            body = parse_hierarchy(entry)
            res += html_list(body, 1)
        if body[-1:] != '\n':
            res += '\n'
    return res


def gen_package(class_hierarchy, package, ctx):
    """Writes a package-info.java file to the package directory with a high
    level description of the package functionality and requirements.

    class_hierarchy -- A tree represented as a list as in parse_hierarchy
    package         -- The package directory as a string
    ctx             -- Context used only for debugging purposes

    """
    if ctx.opts.verbose:
        print 'Generating package description package-info.java...'
    src = source = ''
    decapitalize = lambda s: s[:1].lower() + s[1:] if s else ''
    top_level_entries = filter(is_not_list, class_hierarchy)
    for entry in top_level_entries:
        module_arg = decapitalize(entry[:-5])
        rev = ctx.revs[module_arg][-1:][:0]
        if not rev:
            rev = 'unknown'
        src += 'module "' + module_arg + '" (rev "' + rev + '"), '
    if len(top_level_entries) > 1:
        source += 's'
    source += '\n' + src[:-2]
    html_hierarchy = html_list(parse_hierarchy(class_hierarchy), 0)
    specification = '''
This class hierarchy was generated from the Yang module''' + source + \
' by the <a target="_top" href="https://github.com/Emil-Tail-f/JPyang">' + \
'JPyang</a> plugin of <a target="_top" ' + \
'''href="http://code.google.com/p/pyang/">pyang</a>.
The generated classes may be used to manipulate pieces of configuration data
with NETCONF operations such as edit-config, delete-config and lock. These
operations are typically accessed through the ConfM Java library by
instantiating Device objects and setting up NETCONF sessions with real devices
using a compatible YANG model.

'''
    with open('package-info.java', 'w + ') as f:
        f.write('/**' + java_docify(specification + html_hierarchy) + '''
 *
 * @see <a target="_top" href="https://github.com/Emil-Tail-f/JPyang">''' + \
    'JPyang project page</a>\n * @see <a target="_top" ' + \
    'href="ftp://ftp.rfc-editor.org/in-notes/rfc6020.txt">' + \
    'RFC 6020: YANG - A Data Modeling Language for the Network ' + \
    'Configuration Protocol (NETCONF)</a>\n * @see <a target="_top" ' + \
    'href="ftp://ftp.rfc-editor.org/in-notes/rfc6241.txt">RFC 6241: ' + \
    'Network Configuration Protocol (NETCONF)</a>\n * @see <a ' + \
    'target="_top" href="ftp://ftp.rfc-editor.org/in-notes/rfc6242.txt">' + \
    'RFC 6242: Using the NETCONF Protocol over Secure Shell (SSH)</a>\n' + \
    ' * @see <a target="_top" href="http://www.tail-f.com">Tail-f ' + \
    'Systems</a>\n */\npackage ' + package + ';')

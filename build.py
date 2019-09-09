#!/usr/bin/python
#-*-encoding:utf-8-*-
from __future__ import print_function
import os, sys, shutil, subprocess, logging, time, re, platform, traceback
from datetime import datetime
from copy import copy


class ASimpleNameSpace(object):
    def __str__(self):
        d = {}
        attrs = dir(self)
        for a in attrs:
            if not a.startswith('_'):
                d[a] = eval('self.{0}'.format(a))
        return json.dumps(d, indent=4)


class CMakeCPPBuilder(object):
    def __init__(self):
        self.init_logger()
        self.env = os.environ.copy()
        
    def start(self, args = None):
        '''
        main entry for build
        '''
        try:
            self.parse_args(args = args)
            self.setup_logger()
            self.check_build_environment()
            if 'Windows' == platform.system():
                self.configure_build_win()
                self.start_build_win()
                self.resotre_env()
            elif 'Linux' == platform.system():
                self.configure_build_lin()
                self.start_build_lin()
                self.resotre_env()
        except Exception:
            exc_type, exc_value, exc_traceback = sys.exc_info() # extract most recent Exception info fro sys
            self.logger.info('##############################################################################################')
            self.logger.info('# failed')
            self.logger.info('##############################################################################################')
            traceback.print_exception(exc_type, exc_value, exc_traceback, file=self.logger)
            self.logger.error('[ERROR] failed building {0} due to error above'.format(self.source_dir))
            self.logger.error('see more in log file {0}'.format(self.logger.handlers[1].stream.name))
            self.logger.error('exit at {0}'.format(self.get_time_stamp()))
            
    def parse_args(self, args = None):
        from argparse import ArgumentParser
        from argparse import RawTextHelpFormatter

        # prepare default configurations
        if "Windows" == platform.system():
            self.build_tool = 'Visual Studio'
            self.build_dir = 'build_win'
        elif "Linux" == platform.system():
            self.build_tool = 'make'
            self.build_dir = 'build_lin'
        else:
            self.logger.error('[ERROR] build platform system {0} not support yet'.format(self.build_platform))
            raise Exception('build platform {0} not support yet'.format(self.build_platform))
        
        # help description
        parser = ArgumentParser(
            prog=__file__,
            formatter_class=RawTextHelpFormatter,
            description='build CXX program with cmake + ninja/nmake/msbuild/make in win32/linux',
            epilog='''
[example]
    {0}                     # build with default setttings
    {0} install --verbose   # build install target with verbose log
'''.format(__file__))

        # version info
        parser.add_argument('-v', '--version', help='version', action='version', version='0.1.0')
        
        # common
        parser.add_argument('-vv', '--verbose', help='increase log verbose level', default=False, action='store_true')
        parser.add_argument('-d', '--Debug', help='build Debug target', default=False, action='store_true')
        parser.add_argument('-R', '--RelWithDebInfo', help='build RelWithDebInfo target', default=False, action='store_true')
        parser.add_argument('-r', '--RelMinSize', help='build RelMinSize target', default=False, action='store_true')
        parser.add_argument('-c', '--clean', help='''clean build directory after build is done,
if you need to clean target, pass clean as a target''', default=False, action='store_true')
        parser.add_argument('-C', '--rebuild', help='clean build directory before start build', default=False, action='store_true')
        parser.add_argument('-D', '--build-with-docker', help='''build with docker toolchain container''', default=False, action='store_true')
        parser.add_argument('-I', '--docker-toolchain-image', help='''docker image of build toolchain,
default is davied9/dpc_build_toolchain_centos:latest''', default='davied9/dpc_build_toolchain_centos:latest')
        parser.add_argument('-t', '--build-tool', help='''build toot, the target cmake generate for,
default Windows build tool is Visual Studio,
default Linux build tool is GNU make''', default=self.build_tool)
        parser.add_argument('-s', '--source-directory', help='source directory, where CMakeLists.txt lies', default=os.getcwd())
        parser.add_argument('-w', '--build-directory', help='''build directory, which will be create and used 
as work directory alongside CMakeLists.txt lies''', default=self.build_dir)
        parser.add_argument('targets', help='tagets to build', default=[], nargs='*')
        # linux
        # windows
        parser.add_argument('-M', '--msvc-version', help='''Microsoft Visual Studio Version
Visual Studio 2019 [specify 2019 or 16 as MSVC_VERSION]
Visual Studio 2017 [specify 2017 or 15 as MSVC_VERSION]
Visual Studio 2015 [specify 2015 or 14 as MSVC_VERSION]
Visual Studio 2013 [specify 2013 or 12 as MSVC_VERSION]
Visual Studio 2012 [specify 2012 or 11 as MSVC_VERSION]
''', default=2012)
        
        # parse
        arguments = parser.parse_args(args=args)
        
        # validate
        n_build_type_flags = 0
        n_build_type_flags += 1 if arguments.Debug else 0
        n_build_type_flags += 1 if arguments.RelWithDebInfo else 0
        n_build_type_flags += 1 if arguments.RelMinSize else 0
        if n_build_type_flags > 1:
            raise Exception('too many build flags are set')
        
        # apply configurations
        self.targets = arguments.targets
        self.logger.level = logging.DEBUG if arguments.verbose else logging.INFO
        self.build_type = 'Release' # Release Debug RelWithDebInfo RelMinSize
        if arguments.Debug:
            self.build_type = 'Debug'
        elif arguments.RelWithDebInfo:
            self.build_type = 'RelWithDebInfo'
        elif arguments.RelMinSize:
            self.build_type = 'RelMinSize'
        self.clean_before_build = arguments.rebuild # cleanup build directory before start build
        self.clean_after_build = arguments.clean # cleanup build directory after done build
        self.build_with_docker = arguments.build_with_docker
        self.docker_toolchain_image = arguments.docker_toolchain_image # if specified, docker toolchain will be used as build toolchain
        self.build_tool = arguments.build_tool
        self.source_dir = arguments.source_directory
        self.build_dir = os.path.join(self.source_dir, arguments.build_directory)
        self.msvc_version = int(arguments.msvc_version)
        self.target_architecture = 'x64'
        
    ##############################################################################################
    # windows build procedure
    ##############################################################################################
    def configure_build_win(self):
        '''
        entry for configuration build for windows, make changes if needed
        '''
        self.msvc_community = True
        if 'Visual Studio' == self.build_tool:
            # determine architercture parameter for vcvarsall.bat script && cmake -G option, we do not support x86 host architecture
            # see more info at https://docs.microsoft.com/en-us/cpp/build/building-on-the-command-line?view=vs-2019
            if 'x64' == self.target_architecture:
                cmake_gen_arch_postfix = 'Win64'
                if 'AMD64' == platform.machine():
                    vcvarsall_arch_param = 'x64'
                else:
                    self.logger.error('[ERROR] host architecture {0} not supported'.format(self.target_architecture))
                    raise Exception('host architecture not supported')
            else:
                self.logger.error('[ERROR] target_architecture {0} not supported'.format(self.target_architecture))
                raise Exception('target architecture not supported')
            # build configurations
            if self.msvc_version == 2019 or self.msvc_version == 16:
                self.cmake_gen_target = 'Visual Studio 16 2019'
            elif self.msvc_version == 2017 or self.msvc_version == 15:
                self.cmake_gen_target = 'Visual Studio 15 2017 ' + cmake_gen_arch_postfix
            elif self.msvc_version == 2015 or self.msvc_version == 14:
                self.cmake_gen_target = 'Visual Studio 14 2015 ' + cmake_gen_arch_postfix
            elif self.msvc_version == 2013 or self.msvc_version == 12:
                self.cmake_gen_target = 'Visual Studio 12 2013 ' + cmake_gen_arch_postfix
            elif self.msvc_version == 2012 or self.msvc_version == 11:
                self.cmake_gen_target = 'Visual Studio 11 2012 ' + cmake_gen_arch_postfix
            else:
                self.logger.error('[ERROR] Visual Studio {0} not supported'.format(self.msvc_version))
                raise Exception('Visual Studio {0} not supported'.format(self.msvc_version))
            self.cmake_command = ['cmake', '-G', self.cmake_gen_target, self.source_dir]
            self.make_command_gen = lambda solution_name : ['vcvarsall.bat', vcvarsall_arch_param, '&&', 'msbuild', solution_name, '-p:Configuration='+self.build_type]
        else:
            self.logger.error('[ERROR] unknown build tool {0}'.format(self.build_tool))
            raise Exception('build tool {0} not supported'.format(self.build_tool))
        
    def start_build_win(self):
        '''
        entry for build program
        '''
        self.log_build_configuration()
        self.logger.info('start building at {0}'.format(self.get_time_stamp()))
        if self.clean_before_build:
            if os.path.exists(self.build_dir):
                self.logger.info('removing ' + self.build_dir)
                shutil.rmtree(self.build_dir)
        if not os.path.exists(self.build_dir):
            os.makedirs(self.build_dir)
        os.chdir(self.build_dir)
        if os.path.exists('CMakeCache.txt'):
            self.logger.info('removing ' + os.path.join(self.build_dir, 'CMakeCache.txt'))
            os.remove('CMakeCache.txt')
        # run cmake
        self.logger.info('##############################################################################################')
        self.logger.info('# running cmake')
        self.logger.info('##############################################################################################')
        stdout, stderr = self.run_shell_command(self.cmake_command)
        if len(stderr) > 1:
            raise Exception('running cmake error')
        # find c compiler from cmake log
        c_compiler_matchs = re.findall(r'Check for working C compiler: ([:/.()\w\s]+)\n', stdout)
        if len(c_compiler_matchs) == 0:
            self.logger.error('[ERROR] c compiler not found')
            raise Exception('c compiler not found')
        self.c_compiler = c_compiler_matchs[0]
        self.logger.info('C compiler : {0}'.format(self.c_compiler))
        # find cxx compiler from cmake log
        cxx_compiler_matchs = re.findall(r'Check for working CXX compiler: ([:/.()\w\s]+)\n', stdout)
        if len(c_compiler_matchs) == 0:
            self.logger.error('[ERROR] cxx compiler not found')
            raise Exception('cxx compiler not found')
        self.cxx_compiler = cxx_compiler_matchs[0]
        self.logger.info('CXX compiler : {0}'.format(self.cxx_compiler))
        # validate compilers
        c_compiler_dir = os.path.dirname(self.c_compiler)
        cxx_compiler_dir = os.path.dirname(self.cxx_compiler)
        if c_compiler_dir != cxx_compiler_dir:
            self.logger.error('[ERROR] c compiler && cxx compiler not in same dir, is that all right ?')
            raise Exception('c compiler && cxx compiler not in same dir')
        # determine vcvars64 path && add to system path
        dir, base = os.path.split(self.cxx_compiler)
        while 'Tools' != base and '' != dir and ':/' != dir[1:]:
            dir, base = os.path.split(dir)
        if 'Tools' != base:
            self.logger.error('[ERROR] Tool dir in cxx_compiler_dir {0} not found, maybe Visual Studio installation path tree changed ?'.format(cxx_compiler_dir))
            raise Exception('Tool dir in cxx_compiler_dir not found')
        self.auxilary_tool_dir = os.path.join(dir, 'Auxiliary', 'Build')
        self.logger.info('Auxilary tool path : {0}'.format(self.auxilary_tool_dir))
        # guess solution name
        solution_name = None
        # 1 walk through build dir, find only .sln file
        sln_files = []
        for r, dirs, files in os.walk(self.build_dir):
            for file in files:
                if file.endswith('.sln'):
                    sln_files.append(file)
            break
        if len(sln_files) == 1:
            solution_name = sln_files[0]
            self.logger.info('Solution located {0}'.format(solution_name))
        elif len(sln_files) > 1:
            self.logger.warning('multiple *.sln files located, all not used')
            for sln_file in sln_files:
                self.logger.info('    {0}'.format(sln_file))
        # 2 read from cmake log
        if not solution_name:
            self.logger.warning('trying to match PROJECT_NAME in cmake log')
            solution_name_matchs = re.findall(r'PROJECT_NAME = (\w+)\n', stdout, flags = re.IGNORECASE)
            if len(solution_name_matchs) == 1:
                solution_name = solution_name_matchs[0] + '.sln'
                self.logger.info('Solution located {0}'.format(solution_name))
        if not solution_name:
            self.logger.error('[ERROR] solution name not found');
            raise Exception('solution name not found')
        # determine targets
        self.solution_names = []
        if 0 == len(self.targets):
            self.solution_names.append(solution_name)
        else:
            targets = [t.lower() for t in self.targets]
            if 'all' in targets:
                self.solution_names.append(solution_name)
                targets.remove('all')
            for target in targets:
                if os.path.exists(target + '.vcproj'):
                    self.solution_names.append(target + '.vcproj')
                    self.logger.info('Solution located {0}'.format(self.solution_names[-1]))
                elif os.path.exists(target + '.vcxproj'):
                    self.solution_names.append(target + '.vcxproj')
                    self.logger.info('Solution located {0}'.format(self.solution_names[-1]))
                else:
                    self.logger.error('[ERROR] target {0} not found in build dir {1}'.format(target, self.build_dir))
                    raise Exception('target {0} not found'.format(target))
        # run make command
        self.add_path_to_env(self.auxilary_tool_dir)
        for solution_name in self.solution_names:
            self.logger.info('##############################################################################################')
            self.logger.info('# building target {0}'.format(solution_name))
            self.logger.info('##############################################################################################')
            _, stderr = self.run_shell_command( self.make_command_gen( solution_name = solution_name ) )
            if len(stderr) > 1:
                raise Exception('build error')
        self.logger.info('##############################################################################################')
        self.logger.info('# summery')
        self.logger.info('##############################################################################################')
        self.logger.info('done building at {0}'.format(self.get_time_stamp()))
        
    ##############################################################################################
    # linux build procedure
    ##############################################################################################
    def configure_build_lin(self):
        '''
        entry for configuration build for linux, make changes if needed
        '''
        if 'ninja' == self.build_tool:
            self.cmake_gen_target = 'Ninja'
            self.cmake_command = ['cmake', '-G', self.cmake_gen_target, '-DCMAKE_BUILD_TYPE='+self.build_type, self.source_dir]
            self.make_command = ['ninja']
        elif 'make' == self.build_tool:
            self.cmake_gen_target = 'Unix Makefiles'
            self.cmake_command = ['cmake', '-G', self.cmake_gen_target, '-DCMAKE_BUILD_TYPE='+self.build_type, self.source_dir]
            self.make_command = ['make']
        else:
            self.logger.error('[ERROR] unknown build tool {0}'.format(self.build_tool))
            raise Exception('build tool {0} not supported'.format(self.build_tool))
        
    def start_build_lin(self):
        '''
        entry for build program
        '''
        self.log_build_configuration()
        self.logger.info('start building at {0}'.format(self.get_time_stamp()))
        if self.clean_before_build:
            if os.path.exists(self.build_dir):
                shutil.rmtree(self.build_dir)
        if not os.path.exists(self.build_dir):
            os.makedirs(self.build_dir)
        os.chdir(self.build_dir)
        if os.path.exists('CMakeCache.txt'):
            os.remove('CMakeCache.txt')
        # run cmake
        self.logger.info('##############################################################################################')
        self.logger.info('# running cmake')
        self.logger.info('##############################################################################################')
        _, stderr = self.run_shell_command(self.cmake_command)
        if len(stderr) > 1:
            raise Exception('running cmake error')
        # build targets
        self.logger.info('##############################################################################################')
        self.logger.info('# builiding targets {0}'.format(self.targets))
        self.logger.info('##############################################################################################')
        make_command = copy(self.make_command)
        make_command.extend(self.targets)
        _, stderr = self.run_shell_command(make_command)
        if len(stderr) > 1:
            raise Exception('build error')
        # summery
        self.logger.info('##############################################################################################')
        self.logger.info('# summery')
        self.logger.info('##############################################################################################')
        self.logger.info('done building at {0}'.format(self.get_time_stamp()))
        
    ##############################################################################################
    # utilities
    ##############################################################################################
    def log_build_configuration(self):
        something_to_hide = ['logger']
        something_to_show = ['make_command_gen']
        
        self.logger.debug('##############################################################################################')
        self.logger.debug('# build configurations :')
        self.logger.debug('##############################################################################################')
        attrs = dir(self)
        for attr in attrs:
            val = getattr(self, attr)
            to_show = False
            if not attr.startswith('_') and not callable(val):
                to_show = True
            if attr in something_to_show:
                to_show = True
            if attr in something_to_hide:
                to_show = False
            if to_show:
                self.logger.debug('  {0} : {1}'.format(attr, val))
                
    def resotre_env(self):
        os.chdir(self.source_dir)
        if self.clean_after_build:
            shutil.rmtree(self.build_dir)
        
    def run_shell_command(self, command, log_info=True):
        if log_info:
            self.logger.info('executing {0}'.format(command))
        if 'Windows' == platform.system():
            shell = True
        elif 'Linux' == platform.system():
            shell = False
        p = subprocess.Popen(command, \
            shell=shell, env = self.env, \
            stdout = subprocess.PIPE, stderr = subprocess.PIPE
        )
        stdout, stderr = p.communicate()
        if platform.python_version().startswith('3'):
            stdout = stdout.decode()
            stderr = stderr.decode()
        if log_info:
            self.logger.info(stdout)
            self.logger.error(stderr)
        return stdout, stderr
        
    def close_log_files(self):
        n_handlers = len(self.logger.handlers)
        for i in range(n_handlers-1):
            fh = self.logger.handlers.pop()
            fh.close()
            del fh
            
    def setup_logger(self):
        self.close_log_files()
        log_file_path = os.path.join(self.source_dir, 'build_{0}.log'.format(self.get_time_stamp_word()))
        self.logger.addHandler(logging.FileHandler(log_file_path))
        
    def init_logger(self):
        self.logger = logging.getLogger("CMakeCPPBuilder")
        # add stream handler
        if 0 == len(self.logger.handlers):
            self.logger.addHandler(logging.StreamHandler())
        # add write function for print traceback
        self.logger.write = self.logger.error
        
    def get_time_stamp(self):
        return datetime.fromtimestamp(time.time()).strftime('%Y/%m/%d_%H:%M:%S')
    
    def get_time_stamp_word(self):
        return datetime.fromtimestamp(time.time()).strftime('%Y-%m-%d_%H-%M-%S')
    
    def add_path_to_env(self, path):
        self.env['PATH'] = path + os.pathsep + self.env['PATH']

    def check_tool(self, tool_name, command):
        stdout, stderr = self.run_shell_command([command, '--version'], log_info=False)
        if len(stdout) > 1:
            data_source = stdout
        else:
            data_source = stderr
        version = None
        if not version:
            res = re.findall(r'\d+\.[.\d]+\s\d+\s\(.*\)', data_source, flags=re.IGNORECASE)
            if len(res) == 1:
                version = res[0]
        if not version:
            res = re.findall(r'\d+\.[.\d]+', data_source, flags=re.IGNORECASE)
            if len(res) == 1:
                version = res[0]
        if not version:
            self.logger.debug('{0} : not found'.format(tool_name))
            #self.logger.debug(data_source)
            #self.logger.debug(res)
        else:
            self.logger.debug('{0:8} : {1}'.format(tool_name, res[0]))
    
    def check_build_environment(self):
        self.logger.debug('##############################################################################################')
        self.logger.debug('# checking build environment')
        self.logger.debug('##############################################################################################')
        self.logger.debug(platform.platform())
        self.logger.debug('Python : {0}'.format(platform.python_version()))
        self.check_tool('CMake', 'cmake')
        self.check_tool('GNU Make', 'make')
        self.check_tool('GCC', 'gcc')
        self.check_tool('CC', 'cc')
        self.check_tool('g++', 'g++')
        self.check_tool('c++', 'c++')
        self.check_tool('Ninja', 'ninja')
        
def main():
    CMakeCPPBuilder().start(args = sys.argv[1:])
    
    
if '__main__' == __name__:
    main()


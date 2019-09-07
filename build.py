#!/usr/bin/python
#-*-encoding:utf-8-*-
from __future__ import print_function
import os, sys, shutil, subprocess, logging, time, re, platform
from datetime import datetime
from copy import copy


class ASimpleNameSpace(object):
    def __str__(self):
        d = {}
        attrs = dir(self)
        for a in attrs:
            if not a.startswith('_'):
                d[a] = eval('self.{}'.format(a))
        return json.dumps(d, indent=4)


class CMakeCPPBuilder(object):
    def __init__(self):
        self.logger = logging.getLogger("CMakeCPPBuilder")
        if 0 == len(self.logger.handlers):
            self.logger.addHandler(logging.StreamHandler())
        self.shell_command_shell_flag = False
        self.env = os.environ.copy()
        
    def start(self, source_dir = os.getcwd(), args = None):
        '''
        main entry for build
        '''
        self.source_dir = source_dir
        self.setup_logger()
        try:
            self.parse_args(args = args)
            if 'Windows' == platform.system():
                self.configure_build_win()
                self.start_build_win()
                self.resotre_env_win()
            elif 'Linux' == platform.system():
                self.configure_build_lin()
                self.start_build_lin()
                self.resotre_env_lin()
        except Exception as err:
            self.logger.info('##############################################################################################')
            self.logger.info('# failed')
            self.logger.info('##############################################################################################')
            self.logger.error('[ERROR] failed building {} due to "{}"'.format(self.source_dir, err))
            self.logger.error('see more in log file {}'.format(self.logger.handlers[1].stream.name))
            self.logger.error('exit at {}'.format(self.get_time_stamp()))
            
    def parse_args(self, args = None):
        if not args: return
        from argparse import ArgumentParser
        from argparse import RawTextHelpFormatter

        # help description
        parser = ArgumentParser(
            prog=__file__,
            formatter_class=RawTextHelpFormatter,
            description='build CXX program with cmake + ninja/nmake/msbuild/make in win32/linux',
            epilog='''
[example]
    {0} install
    {0} all install
'''.format(__file__))

        # version info
        parser.add_argument('--version', '-v', help='version', action='version', version='0.1.0')

        # arguments
        parser.add_argument('--verbose', '-vv', help='increase log verbose level', default=False, action='store_true')
        parser.add_argument('targets', help='tagets to build', default=[], nargs='*')
        
        # parse && make configurations in self
        arguments = parser.parse_args(args=args)
        self.targets = arguments.targets
        if arguments.verbose:
            self.logger.level = logging.DEBUG
        else:
            self.logger.level = logging.INFO
        
    ##############################################################################################
    # windows build procedure
    ##############################################################################################
    def configure_build_win(self):
        '''
        entry for configuration build for windows, make changes if needed
        '''
        self.clean_before_build = False # cleanup build directory before start build
        self.clean_after_build = True # cleanup build directory after done build
        self.use_docker_build_toolchain = False
        self.build_type = 'Release' # Release Debug RelWithDebInfo RelMinSize
        self.build_platform = 'Windows'
        self.host_architecture = platform.machine()
        self.target_architecture = 'x64' # 'x64' 'ARM'
        self.shell_command_shell_flag = True
        self.msvc_ver = 2019 # 2012 2015 2017 2019
        self.msvc_community = True
        self.msvc_build_tool = 'Visual Studio' # 'Visual Studio' 'ninja' 'nmake'
        self.build_dir = os.path.join(self.source_dir, 'build_win')
        self.build_method = 'Rebuild' # 'Rebuild' 'Build'
        self.path_split = ';'
        if 'ninja' == self.msvc_build_tool:
            self.logger.error('[ERROR] ninja build system for windows not ready yet'); self.build_state = 'failed'; return
            self.cmake_gen_target = 'Ninja'
            self.ninja_binary_path = 'F:/Develop/ninja/ninja.exe'
            self.cmake_command = ['cmake', '-G', self.cmake_gen_target, '-DCMAKE_MAKE_PROGRAM='+self.ninja_binary_path, \
                '-DCC=cl.exe', '-DCXX=cl.exe', self.source_dir]
        elif 'nmake' == self.msvc_build_tool:
            self.logger.error('[ERROR] nmake build system for windows not ready yet'); self.build_state = 'failed'; return
            self.cmake_gen_target = 'NMake Makefiles'
            self.cmake_command = ['cmake', '-G', self.cmake_gen_target, self.source_dir]
        elif 'Visual Studio' == self.msvc_build_tool:
            # determine architercture parameter for vcvarsall.bat script && cmake -G option, we do not support x86 host architecture
            # see more info at https://docs.microsoft.com/en-us/cpp/build/building-on-the-command-line?view=vs-2019
            if 'x64' == self.target_architecture:
                cmake_g_arch_postfix = 'Win64'
                if 'AMD64' == self.host_architecture:
                    vcvarsall_arch_param = 'x64'
                else:
                    self.logger.error('[ERROR] host architecture {} not supported yet'.format(self.target_architecture))
                    raise Exception('host architecture not supported')
            else:
                self.logger.error('[ERROR] target_architecture {} not supported yet'.format(self.target_architecture))
                raise Exception('target architecture not supported')
            # build configurations
            if self.msvc_ver == 2019:
                self.cmake_gen_target = 'Visual Studio 16 2019'
                self.cmake_command = ['cmake', '-G', self.cmake_gen_target, self.source_dir]
                self.make_command_gen = lambda solution_name : ['vcvarsall.bat', vcvarsall_arch_param, '&&', 'msbuild', solution_name, '-t:'+self.build_method, '-p:Configuration='+self.build_type]
            elif self.msvc_ver == 2017:
                self.cmake_gen_target = 'Visual Studio 15 2017' + ' ' + cmake_g_arch_postfix
                self.cmake_command = ['cmake', '-G', self.cmake_gen_target, self.source_dir]
                self.make_command_gen = lambda solution_name : ['vcvarsall.bat', vcvarsall_arch_param, '&&', 'msbuild', solution_name, '-t:'+self.build_method, '-p:Configuration='+self.build_type]
            else:
                self.logger.error('[ERROR] Visual Studio {} not supported yet'.format(self.msvc_ver))
                raise Exception('Visual Studio {} not supported'.format(self.msvc_ver))
        else:
            self.logger.error('[ERROR] unknown build tool {}'.format(self.msvc_build_tool))
            raise Exception('build tool {} not supported'.format(self.msvc_build_tool))
        
    def start_build_win(self):
        '''
        entry for build program
        '''
        self.log_build_configuration()
        self.logger.info('start building at {}'.format(self.get_time_stamp()))
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
            return
        # find c compiler from cmake log
        c_compiler_matchs = re.findall(r'Check for working C compiler: ([:/.()\w\s]+)\n', stdout)
        if len(c_compiler_matchs) == 0:
            self.logger.error('[ERROR] c compiler not found')
            raise Exception('c compiler not found')
        self.c_compiler = c_compiler_matchs[0]
        self.logger.info('C compiler : {}'.format(self.c_compiler))
        # find cxx compiler from cmake log
        cxx_compiler_matchs = re.findall(r'Check for working CXX compiler: ([:/.()\w\s]+)\n', stdout)
        if len(c_compiler_matchs) == 0:
            self.logger.error('[ERROR] cxx compiler not found')
            raise Exception('cxx compiler not found')
        self.cxx_compiler = cxx_compiler_matchs[0]
        self.logger.info('CXX compiler : {}'.format(self.cxx_compiler))
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
            self.logger.error('[ERROR] Tool dir in cxx_compiler_dir {} not found, maybe Visual Studio installation path tree changed ?'.format(cxx_compiler_dir))
            raise Exception('Tool dir in cxx_compiler_dir not found')
        self.auxilary_tool_dir = os.path.join(dir, 'Auxiliary', 'Build')
        self.logger.info('Auxilary tool path : {}'.format(self.auxilary_tool_dir))
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
            self.logger.info('Solution located {}'.format(solution_name))
        elif len(sln_files) > 1:
            self.logger.warning('multiple *.sln files located, all not used')
            for sln_file in sln_files:
                self.logger.info('    {}'.format(sln_file))
        # 2 read from cmake log
        if not solution_name:
            self.logger.warning('trying to match PROJECT_NAME in cmake log')
            solution_name_matchs = re.findall(r'PROJECT_NAME = (\w+)\n', stdout, flags = re.IGNORECASE)
            if len(solution_name_matchs) == 1:
                solution_name = solution_name_matchs[0] + '.sln'
                self.logger.info('Solution located {}'.format(solution_name))
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
            for target in targets:
                if os.path.exists(target + '.vcproj'):
                    self.solution_names.append(target + '.vcproj')
                elif os.path.exists(target + '.vcxproj'):
                    self.solution_names.append(target + '.vcxproj')
                else:
                    self.logger.error('[ERROR] target {} not found in build dir {}'.format(target, self.build_dir))
                    raise Exception('target {} not found'.format(target))
        # run make command
        self.add_path_to_env(self.auxilary_tool_dir)
        for solution_name in self.solution_names:
            self.logger.info('##############################################################################################')
            self.logger.info('# building target {}'.format(solution_name))
            self.logger.info('##############################################################################################')
            _, stderr = self.run_shell_command( self.make_command_gen( solution_name = solution_name ) )
        self.logger.info('##############################################################################################')
        self.logger.info('# summery')
        self.logger.info('##############################################################################################')
        self.logger.info('done building at {}'.format(self.get_time_stamp()))
        
    def resotre_env_win(self):
        os.chdir(self.source_dir)
        if self.clean_after_build:
            shutil.rmtree(self.build_dir)
        pass
        
    ##############################################################################################
    # linux build procedure
    ##############################################################################################
    def configure_build_lin(self):
        '''
        entry for configuration build for linux, make changes if needed
        '''
        self.clean_before_build = True
        self.use_docker_build_toolchain = False
        self.build_type = 'Release' # Release Debug RelWithDebInfo RelMinSize
        self.build_platform = 'Linux'
        self.target_architecture = 'x64' 
        self.shell_command_shell_flag = False
        self.build_dir = os.path.join(self.source_dir, 'build_lin')
        self.cmake_gen_target = 'Ninja'
        self.cmake_command = ['cmake', '-G', self.cmake_gen_target, self.source_dir]
        self.path_split = ':'
        
    def start_build_lin(self):
        '''
        entry for build program
        '''
        self.log_build_configuration()
        self.logger.info('start building at {}'.format(self.get_time_stamp()))
        if self.clean_before_build:
            if os.path.exists(self.build_dir):
                shutil.rmtree(self.build_dir)
        if not os.path.exists(self.build_dir):
            os.makedirs(self.build_dir)
        os.chdir(self.build_dir)
        if os.path.exists('CMakeCache.txt'):
            os.remove('CMakeCache.txt')
        self.run_shell_command(self.cmake_command)
        self.run_shell_command(self.make_command)
        self.logger.info('done building at {}'.format(self.get_time_stamp()))
                
    def resotre_env_lin(self):
        os.chdir(self.source_dir)
        pass
        
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
                self.logger.debug('  {} : {}'.format(attr, val))
                
    def run_shell_command(self, command):
        self.logger.info('executing {}'.format(command))
        p = subprocess.Popen(command, \
            shell=self.shell_command_shell_flag, env = self.env, \
            stdout = subprocess.PIPE, stderr = subprocess.PIPE
        )
        stdout, stderr = p.communicate()
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
        log_file_path = os.path.join(self.source_dir, 'build_{}.log'.format(self.get_time_stamp_word()))
        self.logger.addHandler(logging.FileHandler(log_file_path))
        
    def get_time_stamp(self):
        return datetime.fromtimestamp(time.time()).strftime('%Y/%m/%d_%H:%M:%S')
    
    def get_time_stamp_word(self):
        return datetime.fromtimestamp(time.time()).strftime('%Y-%m-%d_%H-%M-%S')
    
    def add_path_to_env(self, path):
        self.env['PATH'] = path + self.path_split + self.env['PATH']

    
        
def main():
    CMakeCPPBuilder().start(source_dir = os.getcwd(), args = sys.argv[1:])
    
    
if '__main__' == __name__:
    main()


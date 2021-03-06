import os
import subprocess
import json
import time
import codecs
from multiprocessing import Process, Queue

from asciinema.pty_recorder import PtyRecorder


class Asciicast:

    def __init__(self, f, idle_time_limit):
        self.version = 2
        self.__file = f
        self.idle_time_limit = idle_time_limit

    def stdout(self):
        for line in self.__file:
            time, type, data = json.loads(line)

            if type == 'o':
                yield [time, data]


def load_from_file(f):
    header = json.loads(f.readline())
    idle_time_limit = header.get('idle_time_limit')
    return Asciicast(f, idle_time_limit)


def write_json_lines_from_queue(path, queue):
    with open(path, mode='a', buffering=1) as f:
        for json_value in iter(queue.get, None):
            line = json.dumps(json_value, ensure_ascii=False, indent=None, separators=(', ', ': '))
            f.write(line + '\n')


class incremental_writer():

    def __init__(self, path, header, rec_stdin, start_time_offset=0):
        self.path = path
        self.header = header
        self.rec_stdin = rec_stdin
        self.start_time_offset = start_time_offset
        self.queue = Queue()
        self.stdin_decoder = codecs.getincrementaldecoder('UTF-8')('replace')
        self.stdout_decoder = codecs.getincrementaldecoder('UTF-8')('replace')

    def __enter__(self):
        self.process = Process(
            target=write_json_lines_from_queue,
            args=(self.path, self.queue)
        )
        self.process.start()
        if self.start_time_offset == 0:
            self.queue.put(self.header)
        self.start_time = time.time() - self.start_time_offset
        return self

    def __exit__(self, exc_type, exc_value, exc_traceback):
        self.queue.put(None)
        self.process.join()

    def write_stdin(self, data):
        if self.rec_stdin:
            text = self.stdin_decoder.decode(data)

            if text:
                ts = round(time.time() - self.start_time, 6)
                self.queue.put([ts, 'i', text])

    def write_stdout(self, data):
        text = self.stdout_decoder.decode(data)

        if text:
            ts = round(time.time() - self.start_time, 6)
            self.queue.put([ts, 'o', text])


class Recorder:

    def __init__(self, pty_recorder=None, env=None):
        self.pty_recorder = pty_recorder if pty_recorder is not None else PtyRecorder()
        self.env = env if env is not None else os.environ

    def record(self, path, rec_stdin, user_command, env_whitelist, title, idle_time_limit, start_time_offset=0):
        cols = int(subprocess.check_output(['tput', 'cols']))
        lines = int(subprocess.check_output(['tput', 'lines']))

        vars = filter(None, map((lambda var: var.strip()), env_whitelist.split(',')))
        captured_env = {var: self.env.get(var) for var in vars}

        header = {
            'version': 2,
            'width': cols,
            'height': lines,
            'timestamp': int(time.time()),
            'idle_time_limit': idle_time_limit,
        }

        if captured_env:
            header['env'] = captured_env

        if title:
            header['title'] = title

        command = user_command or self.env.get('SHELL') or 'sh'

        with incremental_writer(path, header, rec_stdin, start_time_offset) as w:
            command_env = os.environ.copy()
            command_env['ASCIINEMA_REC'] = '1'
            self.pty_recorder.record_command(['sh', '-c', command], w, command_env)

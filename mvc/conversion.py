import collections
import errno
import os
import time
import tempfile
import threading
import shutil
import logging

from mvc import execute
from mvc.utils import line_reader
from mvc.video import get_thumbnail_synchronous
from mvc.widgets import get_conversion_directory

logger = logging.getLogger(__name__)

class Conversion(object):
    def __init__(self, video, converter, manager, output_dir=None):
        self.video = video
        self.manager = manager
        if output_dir is None:
            output_dir = get_conversion_directory()
        self.output_dir = output_dir
        self.lines = []
        self.thread = None
        self.popen = None
        self.status = 'initialized'
        self.temp_output = None
        self.error = None
        self.started_at = None
        self.duration = None
        self.progress = None
        self.progress_percent = None
        self.create_thumbnail = False
        self.eta = None
        self.listeners = set()
        self.set_converter(converter)
        logger.info('created %r', self)

    def set_converter(self, converter):
        if self.status != 'initialized':
            raise RuntimeError("can't change converter after starting")
        self.converter = converter
        self.output = os.path.join(self.output_dir,
                                   converter.get_output_filename(self.video))


    def __repr__(self):
        return unicode(self)

    def __str__(self):
        return unicode(self).encode('utf8')

    def __unicode__(self):
        return u'<Conversion (%s) %r -> %r>' % (
            self.converter.name, self.video.filename, self.output)

    def listen(self, f):
        self.listeners.add(f)

    def unlisten(self, f):
        self.listeners.remove(f)

    def notify_listeners(self):
        self.manager.notify_queue.add(self)

    def run(self):
        logger.info('starting %r', self)
        try:
            self.temp_output = tempfile.mktemp(
                dir=os.path.dirname(self.output))
        except EnvironmentError,e :
            logger.exception('while creating temp file for %r',
                             self.output)
            self.error = str(e)
            self.finalize()
            return
        self.thread = threading.Thread(target=self._thread,
                                       name="Thread:%s" % (self,))
        self.thread.setDaemon(True)
        self.thread.start()

    def stop(self):
        logger.info('stopping %r', self)
        self.error = 'manually stopped'
        if self.popen is None:
            status = 'canceled'
            try:
                self.manager.remove(self)
            except ValueError:
                status = 'failed'
                logger.exception('not running and not waiting %s' % (self,))
            self.status = status
            return
        else:
            try:
                self.popen.kill()
                self.popen.wait()
                # set the status transition last, if we had hit an exception
                # then we will transition the next state to 'failed' in
                # finalize()
                self.status = 'canceled'
            except EnvironmentError, e:
                logger.exception('while stopping %s' % (self,))
                self.error = str(e)
        self.popen = None
        self.manager.conversion_finished(self)

    def _thread(self):
        for commandline in self.get_subprocess_arguments(self.temp_output):
            logger.info('commandline: %r', ' '.join(commandline))
            try:
                self.popen = execute.Popen(commandline, bufsize=1)
                self.process_output()
                if self.popen:
                    # if we stop the thread, we can get here after `.stop()`
                    # finishes.
                    self.popen.wait()
            except OSError, e:
                if e.errno == errno.ENOENT:
                    print '%r does not exist' % (self.converter.get_executable(),)
                    self.error = '%r does not exist' % (
                        self.converter.get_executable(),)
                else:
                    logger.exception('OSError in %s' % (self.thread.name,))
                    self.error = str(e)
            except Exception, e:
                logger.exception('in %s' % (self.thread.name,))
                self.error = str(e)

        if self.create_thumbnail:
            self.write_thumbnail_file()
        self.finalize()

    def write_thumbnail_file(self):
        try:
            self._write_thumbnail_file()
        except StandardError:
            logging.warn("Error writing thumbnail", exc_info=True)

    def _write_thumbnail_file(self):
        if self.video.audio_only:
            logging.warning("write_thumbnail_file: audio_only=True "
                    "not writing thumbnail %s", self.video.filename)
            return
        output_basename = os.path.splitext(os.path.basename(self.output))[0]
        logging.info("td: %s ob: %s", self._get_thumbnail_dir(),
                output_basename)
        thumbnail_path = os.path.join(self._get_thumbnail_dir(),
                output_basename + '.png')
        logging.info("creating thumbnail: %s", thumbnail_path)
        width, height = self.converter.get_target_size(self.video)
        get_thumbnail_synchronous(self.video.filename, width, height,
                thumbnail_path)
        if os.path.exists(thumbnail_path):
            logging.info("thumbnail successful: %s", thumbnail_path)
        else:
            logging.warning("get_thumbnail_synchronous() succeeded, but the "
                    "thumbnail file is missing!")

    def _get_thumbnail_dir(self):
        """Get the directory to store thumbnails in it.

        This method will create the directory if it doesn't exist
        """
        thumbnail_dir = os.path.join(self.output_dir, 'thumbnails')
        if not os.path.exists(thumbnail_dir):
            os.mkdir(thumbnail_dir)
        return thumbnail_dir

    def calc_progress_percent(self):
        if not self.duration:
            return 0.0

        if self.create_thumbnail:
            # assume that thumbnail creation takes as long as 2 seconds of
            # video processing
            effective_duration = self.duration + 2.0
        else:
            effective_duration = self.duration
        return self.progress / effective_duration

    def process_output(self):
        self.started_at = time.time()
        self.status = 'converting'
        # We use line_reader, rather than just iterating over the file object,
        # because iterating over the file object gives us all the lines when
        # the process ends, and we're looking for real-time updates.
        for line in line_reader(self.popen.stdout):
            self.lines.append(line) # for debugging, if needed
            try:
                status = self.converter.process_status_line(self.video, line)
            except StandardError:
                logging.warn("error in process_status_line()", exc_info=True)
                continue
            if status is None:
                continue
            updated = set()
            if 'finished' in status:
                self.error = status.get('error', None)
                break
            if 'duration' in status:
                updated.update(('duration', 'progress'))
                self.duration = float(status['duration'])
                if self.progress is None:
                    self.progress = 0.0
            if 'pass1' in status:
                updated.add('progress')
                self.progress = min(float(status['pass1']/2.0),
                                    self.duration)
            if 'pass2' in status:
                updated.add('progress')
                self.progress = min(float(status['pass2']/2.0 + 5),
                                    self.duration)
            if 'progress' in status:
                updated.add('progress')
                self.progress = min(float(status['progress']),
                                    self.duration)
            if 'eta' in status:
                updated.add('eta')
                self.eta = float(status['eta'])

            if updated:
                self.progress_percent = self.calc_progress_percent()
                if 'eta' not in updated:
                    if self.duration and 0 < self.progress_percent < 1.0:
                        progress = self.progress_percent * 100
                        elapsed = time.time() - self.started_at
                        time_per_percent = elapsed / progress
                        self.eta = float(
                            time_per_percent * (100 - progress))
                    else:
                        self.eta = 0.0

                self.notify_listeners()

    def finalize(self):
        self.progress = self.duration
        self.progress_percent = 1.0
        self.eta = 0
        if self.error is None:
            self.status = 'staging'
            self.notify_listeners()
            try:
                self.converter.finalize(self.temp_output, self.output)
            except EnvironmentError, e:
                logger.exception('while trying to move %r to %r after %s',
                                  self.temp_output, self.output, self)
                self.error = str(e)
                self.status = 'failed'
            else:
                self.status = 'finished'
        else:
            if self.temp_output is not None:
                try:
                    os.unlink(self.temp_output)
                except EnvironmentError:
                    pass # ignore errors removing temp files; they may not have
                         # been created
            if self.status != 'canceled':
                self.status = 'failed'
        if True: #self.status == 'finished':
            output_basename = os.path.splitext(os.path.basename(self.output))[0]
            thumbnail_path = os.path.join(self.output_dir,
                    output_basename + '.png')
            get_thumbnail_synchronous(self.video.filename,
                    self.video.width, self.video.height, thumbnail_path)
        if self.status != 'canceled':
            self.notify_listeners()
        logger.info('finished %r; status: %s', self, self.status)

    def get_subprocess_arguments(self, output):
        return (self.converter.get_jobs(self.video, output))


class ConversionManager(object):
    def __init__(self, simultaneous=None):
        self.notify_queue = set()
        self.in_progress = set()
        self.waiting = collections.deque()
        self.simultaneous = simultaneous
        self.running = False
        self.create_thumbnails = False

    def get_conversion(self, video, converter, **kwargs):
        return Conversion(video, converter, self, **kwargs)

    def remove(self, conversion):
        self.waiting.remove(conversion)

    def start_conversion(self, video, converter):
        return self.run_conversion(self.get_conversion(video, converter))

    def run_conversion(self, conversion):
        if (self.simultaneous is not None and
            len(self.in_progress) >= self.simultaneous):
            self.waiting.append(conversion)
        else:
            self._start_conversion(conversion)
            self.running = True
        return conversion

    def _start_conversion(self, conversion):
        self.in_progress.add(conversion)
        conversion.create_thumbnail = self.create_thumbnails
        conversion.run()

    def check_notifications(self):
        if not self.running:
            # don't bother checking if we're not running
            return

        self.notify_queue, changed = set(), self.notify_queue

        for conversion in changed:
            if conversion.status in ('canceled', 'finished', 'failed'):
                self.conversion_finished(conversion)
            for listener in conversion.listeners:
                listener(conversion)

    def conversion_finished(self, conversion):
        self.in_progress.discard(conversion)
        while (self.waiting and self.simultaneous is not None and
               len(self.in_progress) < self.simultaneous):
            c = self.waiting.popleft()
            self._start_conversion(c)
        if not self.in_progress:
            self.running = False

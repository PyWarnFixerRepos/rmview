import logging
import atexit

from PyQt5.QtGui import *
from PyQt5.QtCore import *

# from twisted.internet import reactor
# from twisted.application import internet

from .common import ScreenStreamSignals

log = logging.getLogger('rmview')

from lz4framed import Decompressor, Lz4FramedNoDataError

# try:
#   GRAY16 = QImage.Format_Grayscale16
# except Exception:
#   GRAY16 = QImage.Format_RGB16
# RGB16 = QImage.Format_RGB16



class ReStreamer(QRunnable):

  _stop = False

  ignoreEvents = False

  def __init__(self, ssh, ssh_config):
    super(ReStreamer, self).__init__()
    self.ssh = ssh
    self.ssh_config = ssh_config

    self.signals = ScreenStreamSignals()

  def needsDependencies(self):
    _, out, _ = self.ssh.exec_command("[ -x $HOME/restream ]")
    log.info("%s %s", QFile, QIODevice)
    return out.channel.recv_exit_status() != 0

  def installDependencies(self):
    sftp = self.ssh.open_sftp()
    from stat import S_IXUSR
    fo = QFile(':bin/restream.arm.static')
    fo.open(QIODevice.ReadOnly)
    sftp.putfo(fo, 'restream')
    fo.close()
    sftp.chmod('restream', S_IXUSR)

  def stop(self):
    if self._stop:
        # Already stopped
        return

    self._stop = True

    log.debug("Stopping restream thread...")

    try:
      log.info("Stopping VNC server...")
      self.ssh.exec_command("killall -SIGINT restream")
    except Exception as e:
      log.warning("restream could not be stopped on the reMarkable.")
      log.warning("Although this is not a big problem, it may consume some resources until you restart the tablet.")
      log.warning("You can manually terminate it by running `ssh root@%s killall restream`.", self.ssh.hostname)
      log.error(e)

    log.debug("restream thread stopped")

  @pyqtSlot()
  def run(self):

    # TODO:
    # - determine params
    # - set _restream
    # - figure out picture format


    # rm_version="$(ssh_cmd cat /sys/devices/soc0/machine)"

    if self.ssh.deviceVersion == 1:
      width = 1408
      height = 1872
      bytes_per_pixel = 2
      fb_file = "/dev/fb0"
      # pixel_format = "rgb565le"
      img_format = QImage.Format_RGB16
    if self.ssh.deviceVersion == 2:
      _, out, _ = self.ssh.exec_command("[ -f /dev/shm/swtfb.01 ]")
      oldmem = out.channel.recv_exit_status()
      if oldmem == 0:
        width = 1404
        height = 1872
        bytes_per_pixel = 2
        fb_file="/dev/shm/swtfb.01"
        # pixel_format="rgb565le"
        img_format = QImage.Format_RGB16
      else:
        # WARNING: Completely untested
        width = 1872
        height = 1404
        fb_file = ":mem:"
        if self.ssh.softwareVersion >= (3, 7, 0, 1930):
          log.info("Using the newer :mem: video settings.")
          bytes_per_pixel=2
          # pixel_format="gray16be"
          img_format = QImage.Format_RGB16
          # 90Clockwise and Vertical Flip [transpose=3]
          # TODO: It seems we need to convert from big-endian to little-endian
          # TODO: Need to perform a vertical flip and rotate
        else:
          log.info("Using the older :mem: video settings.")
          bytes_per_pixel=1
          # pixel_format="gray8"
          img_format = QImage.Format_Grayscale8 # >= PyQT 5.5
          # 90CounterClockwise [transpose=2]
          # TODO: Need to perform a rotation
    total_bytes = width * height * bytes_per_pixel

    restream = f"$HOME/restream -h {height} -w {width} -b {bytes_per_pixel} -f {fb_file} "
    log.info("Restream command: %s", restream)

    _, rmstream, rmerr = self.ssh.exec_command(restream)

    data = b''

    try:
      for chunk in Decompressor(rmstream):
        data += chunk
        while len(data) >= total_bytes:
          pix = data[:total_bytes]
          data = data[total_bytes:]
          self.signals.onNewFrame.emit(QImage(pix, width, height, width * 2, img_format))
        if self._stop:
          log.debug('Stopping framebuffer worker')
          break
    except Lz4FramedNoDataError:
      e = rmerr.read().decode('ascii')
      s = rmstream.channel.recv_exit_status()
      log.warning("Frame data stream is empty.\nExit status: %d %s", s, e)

    except Exception as e:
      log.error("Error: %s %s", type(e), e)
      self.signals.onFatalError.emit(e)



  @pyqtSlot()
  def pause(self):
    self.ignoreEvents = True
    self.signals.blockSignals(True)

  @pyqtSlot()
  def resume(self):
    self.ignoreEvents = False
    self.signals.blockSignals(False)

  # @pyqtSlot(int,int,int)
  def pointerEvent(self, x, y, button):
    if self.ignoreEvents: return
    try:
      pass
    except Exception as e:
      log.warning("Not ready to send pointer events! [%s]", e)

  def keyEvent(self, key):
    if self.ignoreEvents: return
    pass

  def emulatePressRelease(self, key):
    pass

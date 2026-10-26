/* SPDX-License-Identifier: GPL-2.0
 * Isolate NV12 DMA-BUF color conversion on Panfrost, without Chromium or decode.
 * cc -Wall -Wextra -Werror zero2w-egl-yuv-color.c $(pkg-config --cflags --libs
 *    libva libva-drm egl glesv2) -lm -o zero2w-egl-yuv-color
 * Use the pinned external VA driver through process-local LIBVA_* variables.
 * Its bare VA surface allocates storage; this test does NOT decode a video.
 */
#include <assert.h>
#include <fcntl.h>
#include <math.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <unistd.h>
#include <linux/dma-buf.h>
#include <va/va.h>
#include <va/va_drm.h>
#include <va/va_drmcommon.h>
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GLES2/gl2.h>
#include <GLES2/gl2ext.h>

#define VA_OK(call) do { VAStatus s = (call); if (s != VA_STATUS_SUCCESS) { \
  fprintf(stderr, "%s: %s\n", #call, vaErrorStr(s)); return 1; } } while (0)

static GLuint shader(GLenum type, const char *src) {
  GLuint object=glCreateShader(type); glShaderSource(object,1,&src,NULL);
  glCompileShader(object); GLint ok; glGetShaderiv(object,GL_COMPILE_STATUS,&ok);
  if (!ok) { char log[2048]; glGetShaderInfoLog(object,sizeof(log),NULL,log); fprintf(stderr,"%s\n",log); }
  assert(ok); return object;
}
static int byte(double v) { return (int)lround(fmax(0.,fmin(255.,v))); }
static void reference(int y, int u, int v, int bt709, int rgb[3]) {
  double kr=bt709 ? .2126 : .299, kb=bt709 ? .0722 : .114;
  double yy=(y-16)/219., cb=(u-128)/224., cr=(v-128)/224.;
  rgb[0]=byte(255*(yy+2*(1-kr)*cr));
  rgb[1]=byte(255*(yy-2*kb*(1-kb)/(1-kr-kb)*cb-2*kr*(1-kr)/(1-kr-kb)*cr));
  rgb[2]=byte(255*(yy+2*(1-kb)*cb));
}
int main(void) {
  int fd=open("/dev/dri/renderD128",O_RDWR|O_CLOEXEC); assert(fd>=0);
  VADisplay va=vaGetDisplayDRM(fd); int major,minor; VA_OK(vaInitialize(va,&major,&minor));
  VASurfaceID id; VA_OK(vaCreateSurfaces(va,VA_RT_FORMAT_YUV420,64,64,&id,1,NULL,0));
  VADRMPRIMESurfaceDescriptor desc;
  VA_OK(vaExportSurfaceHandle(va,id,VA_SURFACE_ATTRIB_MEM_TYPE_DRM_PRIME_2,
                             VA_EXPORT_SURFACE_READ_WRITE|VA_EXPORT_SURFACE_COMPOSED_LAYERS,&desc));
  assert(desc.fourcc==VA_FOURCC_NV12 && desc.num_objects==1 && desc.num_layers==1);
  assert(desc.layers[0].num_planes==2 && desc.width>=64 && desc.height>=64);
  assert(desc.layers[0].object_index[0]==0 && desc.layers[0].object_index[1]==0);
  assert(desc.width%2==0 && desc.height%2==0);
  assert(desc.layers[0].pitch[0]>=desc.width && desc.layers[0].pitch[1]>=desc.width);
  assert((uint64_t)desc.layers[0].offset[0]+(uint64_t)desc.layers[0].pitch[0]*desc.height<=desc.objects[0].size);
  assert((uint64_t)desc.layers[0].offset[1]+(uint64_t)desc.layers[0].pitch[1]*(desc.height/2)<=desc.objects[0].size);
  unsigned char *map=mmap(NULL,desc.objects[0].size,PROT_READ|PROT_WRITE,MAP_SHARED,desc.objects[0].fd,0);
  assert(map!=MAP_FAILED);
  EGLDisplay d=eglGetPlatformDisplay(EGL_PLATFORM_SURFACELESS_MESA,EGL_DEFAULT_DISPLAY,NULL);
  EGLint n; assert(d!=EGL_NO_DISPLAY && eglInitialize(d,NULL,NULL));
  assert(eglBindAPI(EGL_OPENGL_ES_API));
  EGLint ca[]={EGL_SURFACE_TYPE,EGL_PBUFFER_BIT,EGL_RENDERABLE_TYPE,EGL_OPENGL_ES2_BIT,
               EGL_RED_SIZE,8,EGL_GREEN_SIZE,8,EGL_BLUE_SIZE,8,EGL_ALPHA_SIZE,8,EGL_NONE};
  EGLConfig cfg; assert(eglChooseConfig(d,ca,&cfg,1,&n) && n==1);
  EGLint sa[]={EGL_WIDTH,64,EGL_HEIGHT,64,EGL_NONE}, cc[]={EGL_CONTEXT_CLIENT_VERSION,2,EGL_NONE};
  EGLSurface s=eglCreatePbufferSurface(d,cfg,sa); EGLContext c=eglCreateContext(d,cfg,EGL_NO_CONTEXT,cc);
  assert(s!=EGL_NO_SURFACE && c!=EGL_NO_CONTEXT && eglMakeCurrent(d,s,s,c));
  const char *renderer=(const char *)glGetString(GL_RENDERER);
  printf("Renderer: %s\n",renderer); assert(renderer && strstr(renderer,"Panfrost"));
  PFNEGLCREATEIMAGEKHRPROC create=(PFNEGLCREATEIMAGEKHRPROC)eglGetProcAddress("eglCreateImageKHR");
  PFNEGLDESTROYIMAGEKHRPROC destroy=(PFNEGLDESTROYIMAGEKHRPROC)eglGetProcAddress("eglDestroyImageKHR");
  PFNGLEGLIMAGETARGETTEXTURE2DOESPROC bind=(PFNGLEGLIMAGETARGETTEXTURE2DOESPROC)eglGetProcAddress("glEGLImageTargetTexture2DOES");
  assert(create && destroy && bind);
  GLuint vs=shader(GL_VERTEX_SHADER,"attribute vec2 p; varying vec2 uv; void main(){uv=(p+1.)*.5;gl_Position=vec4(p,0.,1.);}");
  GLuint fs=shader(GL_FRAGMENT_SHADER,"#extension GL_OES_EGL_image_external : require\nprecision highp float; varying vec2 uv; uniform samplerExternalOES tex; void main(){gl_FragColor=texture2D(tex,uv);}");
  GLuint prog=glCreateProgram(); glAttachShader(prog,vs);glAttachShader(prog,fs);glBindAttribLocation(prog,0,"p");glLinkProgram(prog);
  GLint ok;glGetProgramiv(prog,GL_LINK_STATUS,&ok);assert(ok);glUseProgram(prog);
  GLfloat quad[]={-1,-1,1,-1,-1,1,1,1};glVertexAttribPointer(0,2,GL_FLOAT,GL_FALSE,0,quad);glEnableVertexAttribArray(0);
  glUniform1i(glGetUniformLocation(prog,"tex"),0);glViewport(0,0,64,64);glDisable(GL_DITHER);
  const int colors[][3]={{63,102,240},{173,42,26},{32,240,118},{219,16,138},{126,128,128},{235,128,128}};
  int max_error=0, wrong_hint_error=0;
  for (unsigned k=0;k<sizeof(colors)/sizeof(colors[0]);k++) {
    struct dma_buf_sync sync={.flags=DMA_BUF_SYNC_START|DMA_BUF_SYNC_WRITE};assert(ioctl(desc.objects[0].fd,DMA_BUF_IOCTL_SYNC,&sync)==0);
    for (unsigned y=0;y<desc.height;y++) memset(map+desc.layers[0].offset[0]+y*desc.layers[0].pitch[0],colors[k][0],desc.width);
    for (unsigned y=0;y<desc.height/2;y++) for(unsigned x=0;x<desc.width;x+=2) {
      unsigned char *p=map+desc.layers[0].offset[1]+y*desc.layers[0].pitch[1]+x;p[0]=colors[k][1];p[1]=colors[k][2];
    }
    sync.flags=DMA_BUF_SYNC_END|DMA_BUF_SYNC_WRITE;assert(ioctl(desc.objects[0].fd,DMA_BUF_IOCTL_SYNC,&sync)==0);
    for (int bt709=0;bt709<=1;bt709++) {
      EGLint attrs[]={EGL_WIDTH,(EGLint)desc.width,EGL_HEIGHT,(EGLint)desc.height,
        EGL_LINUX_DRM_FOURCC_EXT,(EGLint)desc.layers[0].drm_format,
        EGL_DMA_BUF_PLANE0_FD_EXT,desc.objects[0].fd,EGL_DMA_BUF_PLANE0_OFFSET_EXT,(EGLint)desc.layers[0].offset[0],EGL_DMA_BUF_PLANE0_PITCH_EXT,(EGLint)desc.layers[0].pitch[0],
        EGL_DMA_BUF_PLANE1_FD_EXT,desc.objects[0].fd,EGL_DMA_BUF_PLANE1_OFFSET_EXT,(EGLint)desc.layers[0].offset[1],EGL_DMA_BUF_PLANE1_PITCH_EXT,(EGLint)desc.layers[0].pitch[1],
        EGL_YUV_COLOR_SPACE_HINT_EXT,bt709?EGL_ITU_REC709_EXT:EGL_ITU_REC601_EXT,EGL_SAMPLE_RANGE_HINT_EXT,EGL_YUV_NARROW_RANGE_EXT,EGL_NONE};
      EGLImageKHR image=create(d,EGL_NO_CONTEXT,EGL_LINUX_DMA_BUF_EXT,NULL,attrs);assert(image!=EGL_NO_IMAGE_KHR);
      GLuint tex;glGenTextures(1,&tex);glBindTexture(GL_TEXTURE_EXTERNAL_OES,tex);
      glTexParameteri(GL_TEXTURE_EXTERNAL_OES,GL_TEXTURE_MIN_FILTER,GL_NEAREST);glTexParameteri(GL_TEXTURE_EXTERNAL_OES,GL_TEXTURE_MAG_FILTER,GL_NEAREST);
      glTexParameteri(GL_TEXTURE_EXTERNAL_OES,GL_TEXTURE_WRAP_S,GL_CLAMP_TO_EDGE);glTexParameteri(GL_TEXTURE_EXTERNAL_OES,GL_TEXTURE_WRAP_T,GL_CLAMP_TO_EDGE);
      bind(GL_TEXTURE_EXTERNAL_OES,image);glDrawArrays(GL_TRIANGLE_STRIP,0,4);
      unsigned char pixel[4];glReadPixels(32,32,1,1,GL_RGBA,GL_UNSIGNED_BYTE,pixel);assert(glGetError()==GL_NO_ERROR);
      int expected[3],correct709[3];reference(colors[k][0],colors[k][1],colors[k][2],bt709,expected);reference(colors[k][0],colors[k][1],colors[k][2],1,correct709);
      printf("YUV %d,%d,%d matrix=%d RGB=%u,%u,%u expected=%d,%d,%d\n",colors[k][0],colors[k][1],colors[k][2],bt709?709:601,pixel[0],pixel[1],pixel[2],expected[0],expected[1],expected[2]);
      for (int channel=0;channel<3;channel++) {
        int error=(int)fabs((double)pixel[channel]-expected[channel]);if(error>max_error)max_error=error;
        if(!bt709) {error=(int)fabs((double)pixel[channel]-correct709[channel]);if(error>wrong_hint_error)wrong_hint_error=error;}
      }
      glFinish();glDeleteTextures(1,&tex);assert(destroy(d,image));
    }
  }
  printf("max_formula_error=%d wrong_601_hint_max_error_against_709=%d\n",max_error,wrong_hint_error);
  glDeleteProgram(prog);glDeleteShader(vs);glDeleteShader(fs);eglMakeCurrent(d,EGL_NO_SURFACE,EGL_NO_SURFACE,EGL_NO_CONTEXT);
  eglDestroyContext(d,c);eglDestroySurface(d,s);eglTerminate(d);
  munmap(map,desc.objects[0].size);close(desc.objects[0].fd);VA_OK(vaDestroySurfaces(va,&id,1));VA_OK(vaTerminate(va));close(fd);
  if(max_error>2 || wrong_hint_error<10) return 1;
  puts("PASS: both EGL matrices match their CPU formula; wrong hint visibly changes BT.709 colors");
  return 0;
}

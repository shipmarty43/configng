/* SPDX-License-Identifier: GPL-2.0
 * Headless rendering/readback check. Requires libegl-dev and libgles-dev.
 * cc zero2w-gles-smoke.c -lEGL -lGLESv2 -o zero2w-gles-smoke
 */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GLES2/gl2.h>
static GLuint shader(GLenum type, const char *source) {
  GLuint s=glCreateShader(type);
  glShaderSource(s,1,&source,NULL); glCompileShader(s);
  GLint ok=0; glGetShaderiv(s,GL_COMPILE_STATUS,&ok);
  if (!ok) { char log[2048]; glGetShaderInfoLog(s,sizeof(log),NULL,log); fprintf(stderr,"%s\n",log); }
  assert(ok); return s;
}
int main(void) {
  EGLDisplay d=eglGetPlatformDisplay(EGL_PLATFORM_SURFACELESS_MESA,EGL_DEFAULT_DISPLAY,NULL);
  EGLint major,minor,n;
  assert(d != EGL_NO_DISPLAY && eglInitialize(d,&major,&minor));
  assert(eglBindAPI(EGL_OPENGL_ES_API));
  EGLint attrs[]={EGL_SURFACE_TYPE,EGL_PBUFFER_BIT,EGL_RENDERABLE_TYPE,EGL_OPENGL_ES2_BIT,
    EGL_RED_SIZE,8,EGL_GREEN_SIZE,8,EGL_BLUE_SIZE,8,EGL_ALPHA_SIZE,8,EGL_NONE};
  EGLConfig cfg;
  assert(eglChooseConfig(d,attrs,&cfg,1,&n) && n == 1);
  EGLint size[]={EGL_WIDTH,64,EGL_HEIGHT,64,EGL_NONE};
  EGLSurface surface=eglCreatePbufferSurface(d,cfg,size);
  EGLint context_attrs[]={EGL_CONTEXT_CLIENT_VERSION,2,EGL_NONE};
  EGLContext ctx=eglCreateContext(d,cfg,EGL_NO_CONTEXT,context_attrs);
  assert(surface != EGL_NO_SURFACE && ctx != EGL_NO_CONTEXT);
  assert(eglMakeCurrent(d,surface,surface,ctx));
  const char *renderer=(const char *)glGetString(GL_RENDERER);
  printf("Renderer: %s\nVersion: %s\n",renderer,glGetString(GL_VERSION));
  assert(renderer && strstr(renderer,"Panfrost"));
  GLuint vs=shader(GL_VERTEX_SHADER,"attribute vec2 pos; void main(){gl_Position=vec4(pos,0.,1.);}");
  GLuint fs=shader(GL_FRAGMENT_SHADER,"precision mediump float; uniform vec4 color; void main(){gl_FragColor=color;}");
  GLuint prog=glCreateProgram(); glAttachShader(prog,vs); glAttachShader(prog,fs);
  glBindAttribLocation(prog,0,"pos"); glLinkProgram(prog);
  GLint ok; glGetProgramiv(prog,GL_LINK_STATUS,&ok); assert(ok);
  glUseProgram(prog);
  GLfloat vertices[]={-1.f,-1.f,1.f,-1.f,0.f,1.f};
  glVertexAttribPointer(0,2,GL_FLOAT,GL_FALSE,0,vertices); glEnableVertexAttribArray(0);
  glViewport(0,0,64,64); glClearColor(0,0,1,1);
  GLint color=glGetUniformLocation(prog,"color");
  unsigned char pixels[64*64*4];
  for (int i=0; i<100; ++i) {
    glClear(GL_COLOR_BUFFER_BIT);
    glUniform4f(color,i%2,1-i%2,0,1); glDrawArrays(GL_TRIANGLES,0,3);
    glReadPixels(0,0,64,64,GL_RGBA,GL_UNSIGNED_BYTE,pixels);
    assert(glGetError() == GL_NO_ERROR);
    unsigned char *center=&pixels[(32*64+32)*4], *corner=&pixels[(63*64)*4];
    assert(center[0] == (i%2)*255 && center[1] == (1-i%2)*255 && center[2] == 0);
    assert(corner[0] == 0 && corner[1] == 0 && corner[2] == 255);
  }
  puts("100 hardware-rendered frames: shader output and background pixel checks passed");
  glDeleteProgram(prog); glDeleteShader(vs); glDeleteShader(fs);
  eglMakeCurrent(d,EGL_NO_SURFACE,EGL_NO_SURFACE,EGL_NO_CONTEXT);
  eglDestroyContext(d,ctx); eglDestroySurface(d,surface); eglTerminate(d);
  return 0;
}

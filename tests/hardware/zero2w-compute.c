/* SPDX-License-Identifier: GPL-2.0
 * Headless Vulkan compute/readback test, Vulkan 1.0 + core compute only.
 * glslangValidator -V zero2w-compute.comp -o /tmp/zero2w-compute.spv
 * cc -Wall -Wextra -Werror zero2w-compute.c -lvulkan -o /tmp/zero2w-compute
 * Select only the Panfrost ICD; experimental PanVK requires its opt-in flag.
 */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <vulkan/vulkan.h>
#define COUNT 65536u
#define VK(call) do { VkResult r=(call); if (r != VK_SUCCESS) { \
  fprintf(stderr,"%s: VkResult %d\n",#call,r); goto cleanup; } } while (0)

int main(int argc, char **argv) {
  int result=1;
  VkInstance instance=VK_NULL_HANDLE;
  VkDevice device=VK_NULL_HANDLE;
  VkBuffer buffer=VK_NULL_HANDLE;
  VkDeviceMemory memory=VK_NULL_HANDLE;
  VkShaderModule shader=VK_NULL_HANDLE;
  VkDescriptorSetLayout set_layout=VK_NULL_HANDLE;
  VkPipelineLayout layout=VK_NULL_HANDLE;
  VkPipeline pipeline=VK_NULL_HANDLE;
  VkDescriptorPool descriptor_pool=VK_NULL_HANDLE;
  VkCommandPool command_pool=VK_NULL_HANDLE;
  VkFence fence=VK_NULL_HANDLE;
  uint32_t *mapped=NULL, *spirv=NULL;
  if (argc != 2) { fprintf(stderr,"Usage: %s shader.spv\n",argv[0]); return 2; }
  FILE *file=fopen(argv[1],"rb");
  if (!file) { perror("shader"); return 1; }
  if (fseek(file,0,SEEK_END)) { fclose(file); return 1; }
  long size=ftell(file);
  if (size < 20 || size > 1048576 || size%4 || fseek(file,0,SEEK_SET)) { fclose(file); return 1; }
  spirv=malloc((size_t)size);
  if (!spirv || fread(spirv,1,(size_t)size,file) != (size_t)size) {
    fclose(file); free(spirv); return 1;
  }
  fclose(file);
  VkApplicationInfo app={.sType=VK_STRUCTURE_TYPE_APPLICATION_INFO,
    .pApplicationName="Zero2W compute acceptance",.apiVersion=VK_API_VERSION_1_0};
  VkInstanceCreateInfo ic={.sType=VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO,.pApplicationInfo=&app};
  VK(vkCreateInstance(&ic,NULL,&instance));
  uint32_t count=0;
  VK(vkEnumeratePhysicalDevices(instance,&count,NULL));
  if (!count || count > 16) goto cleanup;
  VkPhysicalDevice devices[16], physical=VK_NULL_HANDLE;
  VK(vkEnumeratePhysicalDevices(instance,&count,devices));
  for (uint32_t i=0;i<count;++i) {
    VkPhysicalDeviceProperties p;
    vkGetPhysicalDeviceProperties(devices[i],&p);
    if (p.vendorID==0x13b5 && p.deviceType==VK_PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU
        && strstr(p.deviceName,"Mali-G31")) {
      physical=devices[i];
      printf("Compute device: %s, Vulkan %u.%u.%u\n",p.deviceName,
        VK_VERSION_MAJOR(p.apiVersion),VK_VERSION_MINOR(p.apiVersion),VK_VERSION_PATCH(p.apiVersion));
      break;
    }
  }
  if (!physical) { fputs("No Mali-G31 hardware device; refusing software fallback\n",stderr); goto cleanup; }
  uint32_t family_count=0;
  vkGetPhysicalDeviceQueueFamilyProperties(physical,&family_count,NULL);
  if (!family_count || family_count > 32) goto cleanup;
  VkQueueFamilyProperties families[32];
  vkGetPhysicalDeviceQueueFamilyProperties(physical,&family_count,families);
  uint32_t family=UINT32_MAX;
  for (uint32_t i=0;i<family_count;++i)
    if (families[i].queueCount && (families[i].queueFlags & VK_QUEUE_COMPUTE_BIT)) { family=i; break; }
  if (family==UINT32_MAX) { fputs("No compute queue\n",stderr); goto cleanup; }
  float priority=1;
  VkDeviceQueueCreateInfo qi={.sType=VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO,
    .queueFamilyIndex=family,.queueCount=1,.pQueuePriorities=&priority};
  VkDeviceCreateInfo di={.sType=VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO,.queueCreateInfoCount=1,.pQueueCreateInfos=&qi};
  VK(vkCreateDevice(physical,&di,NULL,&device));
  VkQueue queue;
  vkGetDeviceQueue(device,family,0,&queue);
  VkBufferCreateInfo bi={.sType=VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
    .size=COUNT*sizeof(uint32_t),.usage=VK_BUFFER_USAGE_STORAGE_BUFFER_BIT,.sharingMode=VK_SHARING_MODE_EXCLUSIVE};
  VK(vkCreateBuffer(device,&bi,NULL,&buffer));
  VkMemoryRequirements req;
  vkGetBufferMemoryRequirements(device,buffer,&req);
  VkPhysicalDeviceMemoryProperties mem;
  vkGetPhysicalDeviceMemoryProperties(physical,&mem);
  uint32_t type=UINT32_MAX;
  VkMemoryPropertyFlags wanted=VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT|VK_MEMORY_PROPERTY_HOST_COHERENT_BIT;
  for (uint32_t i=0;i<mem.memoryTypeCount;++i)
    if ((req.memoryTypeBits & (1u<<i)) && (mem.memoryTypes[i].propertyFlags & wanted)==wanted) { type=i; break; }
  if (type==UINT32_MAX) { fputs("No coherent host-visible memory type\n",stderr); goto cleanup; }
  VkMemoryAllocateInfo mi={.sType=VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO,.allocationSize=req.size,.memoryTypeIndex=type};
  VK(vkAllocateMemory(device,&mi,NULL,&memory));
  VK(vkBindBufferMemory(device,buffer,memory,0));
  VK(vkMapMemory(device,memory,0,VK_WHOLE_SIZE,0,(void **)&mapped));
  VkShaderModuleCreateInfo si={.sType=VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO,.codeSize=(size_t)size,.pCode=spirv};
  VK(vkCreateShaderModule(device,&si,NULL,&shader));
  VkDescriptorSetLayoutBinding binding={.binding=0,.descriptorType=VK_DESCRIPTOR_TYPE_STORAGE_BUFFER,
    .descriptorCount=1,.stageFlags=VK_SHADER_STAGE_COMPUTE_BIT};
  VkDescriptorSetLayoutCreateInfo sl={.sType=VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO,.bindingCount=1,.pBindings=&binding};
  VK(vkCreateDescriptorSetLayout(device,&sl,NULL,&set_layout));
  VkPipelineLayoutCreateInfo li={.sType=VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO,.setLayoutCount=1,.pSetLayouts=&set_layout};
  VK(vkCreatePipelineLayout(device,&li,NULL,&layout));
  VkComputePipelineCreateInfo pi={.sType=VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO,.layout=layout,
    .stage={.sType=VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO,.stage=VK_SHADER_STAGE_COMPUTE_BIT,.module=shader,.pName="main"}};
  VK(vkCreateComputePipelines(device,VK_NULL_HANDLE,1,&pi,NULL,&pipeline));
  VkDescriptorPoolSize pool_size={.type=VK_DESCRIPTOR_TYPE_STORAGE_BUFFER,.descriptorCount=1};
  VkDescriptorPoolCreateInfo dpi={.sType=VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO,.maxSets=1,.poolSizeCount=1,.pPoolSizes=&pool_size};
  VK(vkCreateDescriptorPool(device,&dpi,NULL,&descriptor_pool));
  VkDescriptorSet set;
  VkDescriptorSetAllocateInfo dai={.sType=VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO,
    .descriptorPool=descriptor_pool,.descriptorSetCount=1,.pSetLayouts=&set_layout};
  VK(vkAllocateDescriptorSets(device,&dai,&set));
  VkDescriptorBufferInfo db={.buffer=buffer,.offset=0,.range=COUNT*sizeof(uint32_t)};
  VkWriteDescriptorSet write={.sType=VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET,.dstSet=set,.dstBinding=0,
    .descriptorCount=1,.descriptorType=VK_DESCRIPTOR_TYPE_STORAGE_BUFFER,.pBufferInfo=&db};
  vkUpdateDescriptorSets(device,1,&write,0,NULL);
  VkCommandPoolCreateInfo cp={.sType=VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO,.queueFamilyIndex=family};
  VK(vkCreateCommandPool(device,&cp,NULL,&command_pool));
  VkCommandBuffer command;
  VkCommandBufferAllocateInfo ca={.sType=VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO,
    .commandPool=command_pool,.level=VK_COMMAND_BUFFER_LEVEL_PRIMARY,.commandBufferCount=1};
  VK(vkAllocateCommandBuffers(device,&ca,&command));
  VkCommandBufferBeginInfo begin={.sType=VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};
  VK(vkBeginCommandBuffer(command,&begin));
  VkMemoryBarrier before={.sType=VK_STRUCTURE_TYPE_MEMORY_BARRIER,.srcAccessMask=VK_ACCESS_HOST_WRITE_BIT,
    .dstAccessMask=VK_ACCESS_SHADER_READ_BIT|VK_ACCESS_SHADER_WRITE_BIT};
  vkCmdPipelineBarrier(command,VK_PIPELINE_STAGE_HOST_BIT,VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,0,1,&before,0,NULL,0,NULL);
  vkCmdBindPipeline(command,VK_PIPELINE_BIND_POINT_COMPUTE,pipeline);
  vkCmdBindDescriptorSets(command,VK_PIPELINE_BIND_POINT_COMPUTE,layout,0,1,&set,0,NULL);
  vkCmdDispatch(command,COUNT/64,1,1);
  VkMemoryBarrier after={.sType=VK_STRUCTURE_TYPE_MEMORY_BARRIER,.srcAccessMask=VK_ACCESS_SHADER_WRITE_BIT,.dstAccessMask=VK_ACCESS_HOST_READ_BIT};
  vkCmdPipelineBarrier(command,VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,VK_PIPELINE_STAGE_HOST_BIT,0,1,&after,0,NULL,0,NULL);
  VK(vkEndCommandBuffer(command));
  VkFenceCreateInfo fi={.sType=VK_STRUCTURE_TYPE_FENCE_CREATE_INFO};
  VK(vkCreateFence(device,&fi,NULL,&fence));
  VkSubmitInfo submit={.sType=VK_STRUCTURE_TYPE_SUBMIT_INFO,.commandBufferCount=1,.pCommandBuffers=&command};
  for (uint32_t trial=0;trial<8;++trial) {
    uint32_t seed=0xdeadbeefu^(trial*0x9e3779b9u);
    for (uint32_t i=0;i<COUNT;++i) mapped[i]=i^seed;
    VK(vkResetFences(device,1,&fence));
    VK(vkQueueSubmit(queue,1,&submit,fence));
    VK(vkWaitForFences(device,1,&fence,VK_TRUE,10000000000ULL));
    for (uint32_t i=0;i<COUNT;++i) {
      uint32_t expected=i^seed;
      for (uint32_t step=0;step<64;++step) expected=(expected*1664525u+1013904223u)^(i+step);
      if (mapped[i]!=expected) {
        fprintf(stderr,"Mismatch trial %u index %u: GPU=%08x CPU=%08x\n",trial,i,mapped[i],expected);
        goto cleanup;
      }
    }
    printf("Dispatch %u: %u uint32 results match CPU reference\n",trial+1,COUNT);
  }
  puts("Vulkan compute passed: 524288 checked results, 64 arithmetic rounds each");
  result=0;
cleanup:
  if (device) {
    vkDeviceWaitIdle(device);
    if (mapped) vkUnmapMemory(device,memory);
    if (fence) vkDestroyFence(device,fence,NULL);
    if (command_pool) vkDestroyCommandPool(device,command_pool,NULL);
    if (descriptor_pool) vkDestroyDescriptorPool(device,descriptor_pool,NULL);
    if (pipeline) vkDestroyPipeline(device,pipeline,NULL);
    if (layout) vkDestroyPipelineLayout(device,layout,NULL);
    if (set_layout) vkDestroyDescriptorSetLayout(device,set_layout,NULL);
    if (shader) vkDestroyShaderModule(device,shader,NULL);
    if (buffer) vkDestroyBuffer(device,buffer,NULL);
    if (memory) vkFreeMemory(device,memory,NULL);
    vkDestroyDevice(device,NULL);
  }
  if (instance) vkDestroyInstance(instance,NULL);
  free(spirv);
  return result;
}

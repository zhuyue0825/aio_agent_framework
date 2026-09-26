package com.aioagent.business.material;

import com.aioagent.business.auth.CurrentUser;
import java.util.*;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

@RestController
@RequestMapping("/api/v1/conversations/{conversationId}")
public class MaterialController {
    private final CurrentUser users;
    private final MaterialService materials;
    public MaterialController(CurrentUser users,MaterialService materials) { this.users=users; this.materials=materials; }
    @PostMapping("/attachments") public Map<String,Object> upload(@PathVariable UUID conversationId,
            @RequestParam("file") MultipartFile file,Authentication auth) throws java.io.IOException {
        if(file.getSize()>5*1024*1024) throw MaterialService.bad("文件超过 5 MB");
        return materials.upload(users.require(auth),conversationId,file.getOriginalFilename(),file.getBytes());
    }
    @PostMapping("/attachments/reference") public Map<String,Object> reference(@PathVariable UUID conversationId,
            @RequestBody Reference input,Authentication auth) {
        if(input.projectId()==null || input.path()==null) throw MaterialService.bad("请选择工作区文件");
        return materials.reference(users.require(auth),conversationId,input.projectId(),input.path());
    }
    @GetMapping("/attachments/{id}") public Map<String,Object> get(@PathVariable UUID conversationId,@PathVariable UUID id,Authentication auth) {
        return materials.attachment(users.require(auth),conversationId,id,true);
    }
    @PostMapping("/attachments/{id}/retry") public Map<String,Object> retry(@PathVariable UUID conversationId,@PathVariable UUID id,Authentication auth) {
        return materials.retry(users.require(auth),conversationId,id);
    }
    @GetMapping("/knowledge") public Map<String,Object> knowledge(@PathVariable UUID conversationId,Authentication auth) {
        return Map.of("knowledge_ids",materials.selected(users.require(auth),conversationId));
    }
    @PutMapping("/knowledge") public Map<String,Object> select(@PathVariable UUID conversationId,@RequestBody Selection input,Authentication auth) {
        materials.select(users.require(auth),conversationId,input.knowledgeIds());
        return Map.of("knowledge_ids",input.knowledgeIds());
    }
    public record Reference(UUID projectId,String path) {}
    public record Selection(List<String> knowledgeIds) {}
}

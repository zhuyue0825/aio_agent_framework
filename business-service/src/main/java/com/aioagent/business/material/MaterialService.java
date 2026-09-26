package com.aioagent.business.material;

import com.aioagent.business.agent.AgentServiceClient;
import com.aioagent.business.auth.UserAccount;
import com.aioagent.business.common.ApiException;
import com.aioagent.business.conversation.ConversationService;
import com.aioagent.business.project.ProjectService;
import java.nio.file.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import tools.jackson.databind.ObjectMapper;

@Service
public class MaterialService {
    private final JdbcTemplate db;
    private final ConversationService conversations;
    private final ProjectService projects;
    private final AgentServiceClient agent;
    private final ObjectMapper mapper;
    private final Path root;
    public MaterialService(JdbcTemplate db, ConversationService conversations, ProjectService projects,
            AgentServiceClient agent, ObjectMapper mapper, @Value("${AIO_ATTACHMENT_DIR:./data/attachments}") String root) {
        this.db=db; this.conversations=conversations; this.projects=projects; this.agent=agent; this.mapper=mapper;
        this.root=Path.of(root).toAbsolutePath().normalize();
    }
    public static ApiException bad(String message) { return new ApiException(HttpStatus.BAD_REQUEST,"MATERIAL_ERROR",message); }
    public String json(Object value) { return mapper.writeValueAsString(value); }
    @SuppressWarnings("unchecked") public Map<String,Object> decode(String value) { return mapper.readValue(value, Map.class); }
    @SuppressWarnings("unchecked") private List<Map<String,Object>> segments(String value) { return mapper.readValue(value,List.class); }

    public Map<String,Object> upload(UserAccount user, UUID conversation, String name, byte[] bytes) {
        return create(user, conversation, null, name, "upload", "", bytes);
    }
    public Map<String,Object> reference(UserAccount user, UUID conversation, UUID projectId, String path) {
        conversations.require(user,conversation);
        var project=projects.requireMember(projectId,user);
        var response=agent.workspaceFile(project.getWorkspaceRoot(),path,project.getOwner().getId());
        @SuppressWarnings("unchecked") var file=(Map<String,Object>)response.get("file");
        if(file==null || !(file.get("content") instanceof String text)) throw bad("无法读取该工作区文件");
        return create(user,conversation,projectId,Path.of(path).getFileName().toString(),"workspace",path,text.getBytes(StandardCharsets.UTF_8));
    }
    private Map<String,Object> create(UserAccount user, UUID conversation, UUID projectId, String name,String kind,String path,byte[] bytes) {
        conversations.require(user,conversation);
        if(bytes.length==0 || bytes.length>5*1024*1024) throw bad("文件大小须在 1 字节至 5 MB 之间");
        if(name==null || name.isBlank() || name.length()>200 || name.contains("/") || name.contains("\\")) throw bad("文件名不合法");
        if(db.queryForObject("SELECT count(*) FROM chat_attachments WHERE conversation_id=?",Integer.class,conversation)>=30) throw bad("每个对话最多保存 30 个附件");
        UUID id=UUID.randomUUID();
        try { Files.createDirectories(root); Files.write(root.resolve(id+".bin"),bytes,StandardOpenOption.CREATE_NEW); }
        catch(java.io.IOException ex) { throw bad("附件保存失败，请重试"); }
        db.update("INSERT INTO chat_attachments(id,conversation_id,owner_id,project_id,name,source_kind,source_path,byte_size,status) VALUES (?,?,?,?,?,?,?,?,?)",
                id,conversation,user.getId(),projectId,name,kind,path,bytes.length,"PROCESSING");
        process(id,name,bytes);
        return attachment(user,conversation,id,false);
    }
    private void process(UUID id,String name,byte[] bytes) {
        try {
            Map<String,Object> parsed=agent.parseAttachment(name,bytes);
            if(!(parsed.get("segments") instanceof List<?> list) || list.isEmpty()) throw bad("文件未解析出文本");
            db.update("UPDATE chat_attachments SET status='READY',error_message='',segments_json=? WHERE id=?",json(list),id);
        } catch(Exception ex) {
            db.update("UPDATE chat_attachments SET status='FAILED',error_message=? WHERE id=?","解析失败：请使用 UTF-8 文本、代码文件或文字型 PDF（不支持加密/扫描 PDF）；可重试或移除",id);
        }
    }
    public Map<String,Object> retry(UserAccount user,UUID conversation,UUID id) {
        var item=attachment(user,conversation,id,false);
        if("READY".equals(item.get("status"))) return item;
        if(db.update("UPDATE chat_attachments SET status='PROCESSING' WHERE id=? AND (status='FAILED' OR (status='PROCESSING' AND created_at < now()-interval '5 minutes'))",id)==0) throw bad("附件正在处理中，请稍后重试");
        try { process(id,item.get("name").toString(),Files.readAllBytes(root.resolve(id+".bin"))); }
        catch(java.io.IOException ex) { db.update("UPDATE chat_attachments SET status='FAILED',error_message='原文件不可用，请重新上传' WHERE id=?",id); }
        return attachment(user,conversation,id,false);
    }
    public Map<String,Object> attachment(UserAccount user,UUID conversation,UUID id,boolean full) {
        conversations.require(user,conversation);
        var rows=db.queryForList("SELECT * FROM chat_attachments WHERE id=? AND conversation_id=? AND owner_id=?",id,conversation,user.getId());
        if(rows.isEmpty()) throw new ApiException(HttpStatus.NOT_FOUND,"ATTACHMENT_NOT_FOUND","附件不存在");
        var row=rows.getFirst();
        if(row.get("project_id")!=null) projects.requireMember((UUID)row.get("project_id"),user);
        Map<String,Object> item=new LinkedHashMap<>();
        for(String key:List.of("id","name","source_kind","source_path","byte_size","status","error_message","created_at")) item.put(key,row.get(key).toString());
        if(full) item.put("segments",segments(row.get("segments_json").toString()));
        return item;
    }
    public List<String> selected(UserAccount user,UUID conversation) {
        conversations.require(user,conversation);
        var rows=db.queryForList("SELECT knowledge_ids_json FROM chat_knowledge_selection WHERE conversation_id=?",String.class,conversation);
        if(rows.isEmpty()) return List.of();
        return mapper.readValue(rows.getFirst(),List.class);
    }
    public void select(UserAccount user,UUID conversation,List<String> ids) {
        conversations.require(user,conversation);
        validateKnowledge(ids);
        db.update("INSERT INTO chat_knowledge_selection VALUES (?,?) ON CONFLICT(conversation_id) DO UPDATE SET knowledge_ids_json=excluded.knowledge_ids_json",conversation,json(ids));
    }
    public static void validateKnowledge(List<String> ids) {
        if(ids==null || ids.size()>1 || ids.stream().anyMatch(id->!"duretrieval".equals(id))) throw bad("知识库选择无效");
    }
    public Map<String,Object> snapshot(UserAccount user,UUID conversation,List<UUID> ids,List<String> knowledge) {
        if(ids.size()>5 || new HashSet<>(ids).size()!=ids.size()) throw bad("每条消息最多添加 5 个不同附件");
        validateKnowledge(knowledge);
        List<Map<String,Object>> attachments=new ArrayList<>();
        for(UUID id:ids) {
            var item=attachment(user,conversation,id,false);
            if(!"READY".equals(item.get("status"))) throw bad("附件尚未处理完成，请等待、重试或移除");
            attachments.add(item);
        }
        select(user,conversation,knowledge);
        return Map.of("attachments",attachments,"knowledge_ids",knowledge);
    }
    public Map<String,Object> execution(UserAccount user,UUID conversation,String metadata) {
        var stored=decode(metadata);
        List<Map<String,Object>> attachments=new ArrayList<>();
        if(stored.get("attachments") instanceof List<?> list) for(Object value:list) {
            if(value instanceof Map<?,?> row) attachments.add(attachment(user,conversation,UUID.fromString(row.get("id").toString()),true));
        }
        return Map.of("attachments",attachments,"knowledge_ids",stored.getOrDefault("knowledge_ids",List.of()));
    }
}

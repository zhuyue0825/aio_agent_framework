package com.aioagent.business.material;

import com.aioagent.business.agent.AgentServiceClient;
import com.aioagent.business.config.AppProperties;
import com.aioagent.business.common.ApiException;
import java.nio.file.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.sql.*;
import java.util.*;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.*;

@RestController
public class KnowledgeController {
    private final String url,secretFile;
    private final AppProperties properties;
    private final JdbcTemplate business;
    private final MaterialService materials;
    public KnowledgeController(@Value("${RAG_DB_URL:}") String url,@Value("${RAG_DB_ENV_FILE:}") String secretFile,
            AppProperties properties,JdbcTemplate business,MaterialService materials) {
        this.url=url; this.secretFile=secretFile; this.properties=properties; this.business=business; this.materials=materials;
    }
    private Connection connection() throws Exception {
        if(url.isBlank()) throw new IllegalStateException("RAG disabled");
        String password=Files.readAllLines(Path.of(secretFile)).stream().filter(s->s.startsWith("RAG_DB_PASSWORD=")).findFirst().orElseThrow().substring(16).trim();
        var conn=DriverManager.getConnection(url,"rag_lab",password);
        conn.setReadOnly(true);
        try(var statement=conn.createStatement(); var rows=statement.executeQuery("SELECT value->'config'->>'model' AS model,value->'config'->>'dimensions' AS dims FROM rag_lab.metadata WHERE id=1")) {
            if(!rows.next() || !"BAAI/bge-m3".equals(rows.getString(1)) || !"1024".equals(rows.getString(2))) {
                conn.close(); throw new IllegalStateException("Knowledge model mismatch");
            }
        } catch(Exception ex) { conn.close(); throw ex; }
        return conn;
    }
    @GetMapping("/api/v1/knowledge-bases") public Map<String,Object> catalog() {
        boolean available=false;
        try(var conn=connection()) { available=true; } catch(Exception ignored) {}
        return Map.of("knowledge_bases",List.of(Map.of("id","duretrieval","name","中文通用检索演示库",
                "description","DuRetrieval · 10,000 篇中文资料，用于检索演示；不含当前项目文档", "available",available)));
    }
    @GetMapping("/api/v1/knowledge-bases/duretrieval/documents/{id}") public Map<String,Object> document(@PathVariable String id) {
        if(!id.matches("[a-f0-9]{32}")) throw MaterialService.bad("文档编号无效");
        try(var conn=connection();var query=conn.prepareStatement("SELECT id,text,start_char,end_char FROM rag_lab.chunks WHERE parent_id=? ORDER BY start_char")) {
            query.setString(1,id);
            List<Map<String,Object>> segments=new ArrayList<>();
            try(var rows=query.executeQuery()) { while(rows.next()) segments.add(Map.of("id",rows.getString(1),"text",rows.getString(2),"location","字符 "+rows.getInt(3)+"–"+rows.getInt(4))); }
            return Map.of("name","DuRetrieval / "+id,"segments",segments);
        } catch(Exception ex) { throw new ApiException(HttpStatus.SERVICE_UNAVAILABLE,"KNOWLEDGE_UNAVAILABLE","知识库暂不可用"); }
    }
    @PostMapping("/internal/v1/knowledge/search") public Map<String,Object> search(
            @RequestHeader(AgentServiceClient.INTERNAL_TOKEN_HEADER) String token,@RequestBody Search input) {
        if(!MessageDigest.isEqual(properties.getAgent().getInternalToken().getBytes(StandardCharsets.UTF_8),token.getBytes(StandardCharsets.UTF_8)))
            throw new ApiException(HttpStatus.UNAUTHORIZED,"INVALID_INTERNAL_TOKEN","内部服务凭证无效");
        if(input.vector()==null || input.vector().size()!=1024 || input.vector().stream().anyMatch(x->x==null || !Double.isFinite(x))) throw MaterialService.bad("查询向量不合法");
        if(input.vector().stream().allMatch(x->x==0)) throw MaterialService.bad("查询向量不能全为零");
        var authorized=business.queryForList("SELECT m.metadata_json FROM agent_runs r JOIN messages m ON m.id=r.user_message_id WHERE r.id=? AND r.requested_by_id=? AND r.status='RUNNING'",String.class,input.runId(),input.userId());
        if(authorized.isEmpty() || !(materials.decode(authorized.getFirst()).get("knowledge_ids") instanceof List<?> ids) || !ids.contains("duretrieval"))
            throw new ApiException(HttpStatus.FORBIDDEN,"KNOWLEDGE_NOT_SELECTED","该任务未选择知识库");
        String sql="""
            WITH scored AS MATERIALIZED (SELECT id,parent_id,embedding <=> ?::vector distance FROM rag_lab.chunks),
            best AS (SELECT DISTINCT ON(parent_id) * FROM scored ORDER BY parent_id,distance,id),
            top_docs AS (SELECT * FROM best ORDER BY distance,parent_id LIMIT 5)
            SELECT b.parent_id,b.id,1-b.distance,c.text,c.start_char,c.end_char
            FROM top_docs b JOIN rag_lab.chunks c ON c.id=b.id ORDER BY b.distance,b.parent_id
            """;
        try(var conn=connection();var query=conn.prepareStatement(sql)) {
            query.setString(1,input.vector().toString());
            List<Map<String,Object>> found=new ArrayList<>();
            try(var rows=query.executeQuery()) { while(rows.next()) found.add(Map.of("document_id",rows.getString(1),"chunk_id",rows.getString(2),"score",rows.getDouble(3),"text",rows.getString(4),"location","字符 "+rows.getInt(5)+"–"+rows.getInt(6))); }
            return Map.of("results",found);
        } catch(Exception ex) { throw new ApiException(HttpStatus.SERVICE_UNAVAILABLE,"KNOWLEDGE_UNAVAILABLE","知识库检索失败，请稍后重试"); }
    }
    public record Search(UUID runId,UUID userId,List<Double> vector) {}
}

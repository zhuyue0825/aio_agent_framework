package com.aioagent.business.run;

import com.aioagent.business.config.AppProperties;
import java.nio.charset.StandardCharsets;
import java.util.UUID;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.InitializingBean;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.data.redis.connection.Message;
import org.springframework.data.redis.connection.MessageListener;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.listener.ChannelTopic;
import org.springframework.data.redis.listener.RedisMessageListenerContainer;
import org.springframework.stereotype.Component;

@Component
@ConditionalOnProperty(prefix = "app.redis", name = "enabled", havingValue = "true")
public class RedisRunEventBroadcaster implements RunEventBroadcaster, MessageListener, InitializingBean {

    private static final Logger log = LoggerFactory.getLogger(RedisRunEventBroadcaster.class);
    private final String instanceId = UUID.randomUUID().toString();
    private final StringRedisTemplate redis;
    private final RedisMessageListenerContainer container;
    private final RunEventRepository events;
    private final SseRunEventHub hub;
    private final String channel;

    public RedisRunEventBroadcaster(
            StringRedisTemplate redis,
            RedisMessageListenerContainer container,
            RunEventRepository events,
            SseRunEventHub hub,
            AppProperties properties) {
        this.redis = redis;
        this.container = container;
        this.events = events;
        this.hub = hub;
        this.channel = properties.getRedis().getEventChannel();
    }

    @Override
    public void afterPropertiesSet() {
        container.addMessageListener(this, ChannelTopic.of(channel));
    }

    @Override
    public void broadcast(RunEvent event) {
        hub.publish(event);
        redis.convertAndSend(channel, instanceId + ":" + event.getId());
    }

    @Override
    public void onMessage(Message message, byte[] pattern) {
        String payload = new String(message.getBody(), StandardCharsets.UTF_8);
        int separator = payload.lastIndexOf(':');
        if (separator <= 0 || payload.substring(0, separator).equals(instanceId)) {
            return;
        }
        try {
            long eventId = Long.parseLong(payload.substring(separator + 1));
            events.findByIdWithRun(eventId).ifPresent(hub::publish);
        } catch (NumberFormatException exception) {
            log.debug("Ignoring malformed Redis run event notification");
        }
    }
}

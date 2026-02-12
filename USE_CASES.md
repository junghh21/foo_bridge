# Reverse Proxy - Use Cases and Test Scenarios

## Use Case 1: Basic Echo Service

**Scenario:** Simple request-response through tunnel

**Flow:**
```
Client (localhost:11434) 
  → HTTP POST request
    → Client Tunnel (parses HTTP)
      → WSS to Proxy (JSON)
        → Proxy routes to Echo Server
          → Echo Server processes (returns same data)
            → Response back through proxy
              → HTTP response to client
```

**Expected Outcome:**
- Client sends data
- Server echoes it back
- Works transparently

**Test Points:**
- Request successfully transmitted
- Response received correctly
- Data integrity preserved

---

## Use Case 2: Remote Database Connection

**Scenario:** Access remote PostgreSQL through tunnel

**Local:** 
```
postgresql://localhost:5432
```

**Remote:**
```
PostgreSQL server registered as "postgres_main" in proxy
```

**Flow:**
```
Application (localhost:5432)
  → PostgreSQL Protocol over HTTP/WSS tunnel
    → Proxy routes to remote DB
      → Query execution
        → Results back
```

**Expected Outcome:**
- Transparent database connection
- Queries executed on remote server
- Results returned to local client

**Test Points:**
- Connection establishment
- Query transmission
- Result parsing
- Error handling for DB errors

---

## Use Case 3: Multiple Parallel Clients

**Scenario:** Multiple clients connecting to same service

**Setup:**
```
Client 1 (localhost:8081) → Calculator service
Client 2 (localhost:8081) → Calculator service (different request)
```

**Flow:**
```
Client 1: add(1,2)  ─┐
                     ├→ Proxy routes by request_id
Client 2: mul(3,4)  ─┤
                    Response 1 (add=3): back to Client 1
                    Response 2 (mul=12): back to Client 2
```

**Expected Outcome:**
- No cross-contamination of requests
- Each client gets correct response
- Concurrent handling works

**Test Points:**
- Request ID uniqueness
- Response routing accuracy
- No data mixing

---

## Use Case 4: Server Disconnect and Reconnect

**Scenario:** Backend server crashes then restarts

**Timeline:**
```
Time T0: Server connected, handling requests
Time T1: Server crashes
         - Intermediate requests fail
         - New client requests queue or timeout
Time T2: Server restarts
         - Re-registers with proxy
         - New requests go through
```

**Expected Outcome:**
- Initial requests fail gracefully
- Server automatically reconnects
- New requests succeed after reconnect
- No proxy corruption

**Test Points:**
- Server detect when removed from registry
- Graceful error response to clients
- Successful reconnection
- Recovery without manual intervention

---

## Use Case 5: Client Disconnect and Reconnect

**Scenario:** Local client crashes then reconnects

**Timeline:**
```
Time T0: Client tunnel active, forwarding requests
Time T1: Client crashes
         - Tunnel connection drops
         - Proxy cleans up client connection
Time T2: New tunnel instance connects
         - Re-registers client interest
         - Previous requests orphaned
```

**Expected Outcome:**
- Smooth handling of disconnected client
- New client can connect
- No orphaned requests on server

**Test Points:**
- Connection cleanup
- Resource recovery
- New tunnel independent

---

## Use Case 6: Request Timeout

**Scenario:** Server takes too long to respond

**Timeline:**
```
Time T0: Client sends request
Time T0+10s: Server still processing
Time T0+30s: Client times out
Time T0+45s: Server finally responds (but no one listening)
```

**Expected Outcome:**
- Client times out with appropriate error
- Server response discarded
- Resources cleaned up
- Connection remains healthy

**Test Points:**
- Timeout trigger
- Error propagation to client
- Response queue cleanup
- No connection corruption

---

## Use Case 7: Multiple Backend Servers

**Scenario:** Load distribution across multiple services

**Setup:**
```
Calculator1 (calculator_1)
Calculator2 (calculator_2)
Both handling same request types
```

**Flow:**
```
Client connects to calculator_1:
  POST /calc → calculator_1 → response

Different client connects to calculator_2:
  POST /calc → calculator_2 → response
```

**Expected Outcome:**
- Independent server chains
- No interference between services
- Each service maintains own stats

**Test Points:**
- Service isolation
- Correct routing per server
- Statistics per service

---

## Use Case 8: Large Data Transfer

**Scenario:** Transfer of large payload (1MB+)

**Flow:**
```
Client sends:
  Large JSON body ~1MB
  →→→ Tunnel chunks/buffers
    →→→ Proxy forwards completely
      →→→ Server processes
        →→→ Large response back
```

**Expected Outcome:**
- Complete data transfer
- No truncation
- Memory efficient
- Performance acceptable

**Test Points:**
- Buffer handling
- Memory usage
- Transfer speed
- Integrity of large payloads

---

## Use Case 9: Network Delay Simulation

**Scenario:** High latency network (1000ms+)

**Flow:**
```
Client sends request
  250ms delay → Proxy
    250ms delay → Server
      250ms processing
    250ms delay → Proxy
  250ms delay → Client
  = 1.25 seconds total
```

**Expected Outcome:**
- Requests still complete
- May hit timeout if too high
- No data corruption
- Performance degradation expected

**Test Points:**
- Timeout threshold
- Latency tolerance
- Data consistency

---

## Use Case 10: SSL Certificate Verification Failure

**Scenario:** Client or server with untrusted certificate

**Setup:**
```
verify_ssl=False (current development mode)
```

**Expected Outcome:**
- Connections succeed despite untrusted cert
- Encrypted but not authenticated
- Clear warnings in logs

**Test Points:**
- Connection despite cert issue
- Functionality unaffected
- Proper logging

---

## Use Case 11: Proxy Server Restart

**Scenario:** Main proxy service crashes and restarts

**Timeline:**
```
Time T0: Proxy running, all services connected
Time T1: Proxy crashes
         - All connections drop
         - Active requests fail
Time T2: Proxy restarts
         - Services need to re-register
         - New clients can connect
```

**Expected Outcome:**
- Graceful degradation during downtime
- Auto-reconnection after restart
- No data loss (idempotent operations)
- Full functionality restored

**Test Points:**
- Connection drop handling
- Re-registration success
- Client recovery
- Service availability post-restart

---

## Use Case 12: Partial Message Loss

**Scenario:** Network packet loss or corruption

**Flow:**
```
Client sends request
  SENT: {"operation": "add", "a": 1, "b": 2}
  RECEIVED: {"operation": "ad"} ← corrupted, incomplete
```

**Expected Outcome:**
- JSON parsing error caught
- Error response to client
- Connection remains healthy
- No crashes

**Test Points:**
- JSON validation
- Partial message handling
- Error recovery
- Connection stability

---

## Use Case 13: Rapid Fire Requests

**Scenario:** Many requests in quick succession

**Flow:**
```
Client 1: Request 1, 2, 3, 4, 5 (rapid)
Client 2: Request 1, 2, 3, 4, 5 (rapid)
Proxy must:
  - Track all 10 request IDs
  - Route responses correctly
  - Handle queuing
```

**Expected Outcome:**
- All requests processed
- Correct response routing
- No request loss
- Queue depth acceptable

**Test Points:**
- Request ID generation uniqueness
- Response mapping accuracy
- Queue handling
- Performance under load

---

## Use Case 14: Clean Shutdown

**Scenario:** Graceful service termination

**Flow:**
```
Signal: SIGTERM received
  - Stop accepting new connections
  - Wait for in-flight requests
  - Close existing connections
  - Cleanup resources
  - Exit cleanly
```

**Expected Outcome:**
- No resource leaks
- No orphaned connections
- Clients get error/timeout
- Service exits cleanly

**Test Points:**
- In-flight request completion
- Connection closure
- Resource cleanup
- Exit code

---

## Use Case 15: Service Degradation Management

**Scenario:** One service slow, others normal

**Setup:**
```
Service A: Normal (100ms response)
Service B: Slow (5000ms response)
Service C: Normal (100ms response)
```

**Expected Outcome:**
- Slow service doesn't block others
- Clients connected to B wait longer
- A and C work normally
- No cascading failures

**Test Points:**
- Service independence
- Timeout handling per service
- No resource starvation
- Load balancing awareness

---

## Use Case 16: Memory Leak Detection

**Scenario:** Extended operation with connection churn

**Flow:**
```
100 hours of operation
  - Services connecting/disconnecting
  - Clients connecting/disconnecting
  - Thousands of requests
  - Monitor memory usage
```

**Expected Outcome:**
- Memory stable (no growth)
- No resource exhaustion
- All requests still proces
s
- Connection count tracked

**Test Points:**
- Memory growth rate
- Connection cleanup
- Queue draining
- Statistics accuracy

---

## Test Priority Matrix

| Use Case | Priority | Complexity | Time |
|----------|----------|-----------|------|
| #1 Basic Echo | P0 | Low | 5min |
| #2 Remote DB | P1 | High | 30min |
| #3 Multiple Clients | P0 | Medium | 10min |
| #4 Server Reconnect | P0 | Medium | 15min |
| #5 Client Reconnect | P1 | Medium | 10min |
| #6 Request Timeout | P1 | Low | 10min |
| #7 Multiple Servers | P1 | Low | 5min |
| #8 Large Data | P1 | Medium | 15min |
| #9 Network Delay | P2 | Medium | 20min |
| #10 SSL Failure | P2 | Low | 5min |
| #11 Proxy Restart | P0 | High | 20min |
| #12 Message Loss | P2 | Medium | 15min |
| #13 Rapid Fire | P1 | Medium | 10min |
| #14 Clean Shutdown | P1 | Medium | 10min |
| #15 Degradation | P2 | Medium | 15min |
| #16 Memory Leak | P2 | High | 60min |

---

## Implementation Notes

Each test should verify:
1. **Functional Correctness**: Does it do what it should?
2. **Error Handling**: Appropriate error responses
3. **Resource Cleanup**: No leaks or orphaned connections
4. **Connection Health**: Remains stable after error
5. **Data Integrity**: No corruption or loss
6. **Performance**: Meets timing requirements


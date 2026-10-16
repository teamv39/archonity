package com.v39a.model;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.ArrayList;
import java.util.List;

@JsonInclude(JsonInclude.Include.ALWAYS)
public class BranchIR {
    @JsonProperty("id")
    private String id;

    @JsonProperty("line")
    private int line;

    @JsonProperty("guard")
    private List<String> guard = new ArrayList<>();

    @JsonProperty("kind")
    private String kind; // "if", "else-if"

    @JsonProperty("condition_text")
    private String conditionText;

    @JsonProperty("refers_to")
    private List<String> refersTo = new ArrayList<>();

    @JsonProperty("early_exit")
    private EarlyExit earlyExit = new EarlyExit(false, false);

    @JsonProperty("then_calls")
    private List<String> thenCalls = new ArrayList<>();

    @JsonProperty("else_calls")
    private List<String> elseCalls = new ArrayList<>();

    public BranchIR() {}

    public BranchIR(String id, int line, List<String> guard, String kind, String conditionText, List<String> refersTo, EarlyExit earlyExit, List<String> thenCalls, List<String> elseCalls) {
        this.id = id;
        this.guard = guard != null ? guard : new ArrayList<>();
        this.line = line;
        this.kind = kind;
        this.conditionText = conditionText;
        this.refersTo = refersTo != null ? refersTo : new ArrayList<>();
        this.earlyExit = earlyExit != null ? earlyExit : new EarlyExit(false, false);
        this.thenCalls = thenCalls != null ? thenCalls : new ArrayList<>();
        this.elseCalls = elseCalls != null ? elseCalls : new ArrayList<>();
    }

    public int getLine() {
        return line;
    }

    public void setLine(int line) {
        this.line = line;
    }

    public String getKind() {
        return kind;
    }

    public void setKind(String kind) {
        this.kind = kind;
    }

    public String getConditionText() {
        return conditionText;
    }

    public void setConditionText(String conditionText) {
        this.conditionText = conditionText;
    }

    public List<String> getRefersTo() {
        return refersTo;
    }

    public void setRefersTo(List<String> refersTo) {
        this.refersTo = refersTo;
    }

    public String getId() {
        return id;
    }

    public List<String> getGuard() {
        return guard;
    }

    public EarlyExit getEarlyExit() {
        return earlyExit;
    }

    public void setEarlyExit(EarlyExit earlyExit) {
        this.earlyExit = earlyExit != null ? earlyExit : new EarlyExit(false, false);
    }

    public List<String> getThenCalls() {
        return thenCalls;
    }

    public void setThenCalls(List<String> thenCalls) {
        this.thenCalls = thenCalls;
    }

    public List<String> getElseCalls() {
        return elseCalls;
    }

    public void setElseCalls(List<String> elseCalls) {
        this.elseCalls = elseCalls;
    }

    /** Заканчивается ли плечо return/throw: then и else по отдельности. */
    public static class EarlyExit {
        @JsonProperty("then")
        private boolean thenArm;

        @JsonProperty("else")
        private boolean elseArm;

        public EarlyExit() {}

        public EarlyExit(boolean thenArm, boolean elseArm) {
            this.thenArm = thenArm;
            this.elseArm = elseArm;
        }

        public boolean isThenArm() {
            return thenArm;
        }

        public boolean isElseArm() {
            return elseArm;
        }
    }
}

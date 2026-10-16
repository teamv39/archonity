package com.v39a.model;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.ArrayList;
import java.util.List;

@JsonInclude(JsonInclude.Include.ALWAYS)
public class CallIR {
    @JsonProperty("call_site_id_guess")
    private String callSiteIdGuess;

    @JsonProperty("file")
    private String file;

    @JsonProperty("line")
    private int line;

    @JsonProperty("col")
    private int col;

    @JsonProperty("callee")
    private String callee;

    @JsonProperty("receiver")
    private String receiver;

    @JsonProperty("kind")
    private String kind; // SAME_CLASS, ENUM, CONSTRUCTOR, OTHER

    @JsonProperty("arg_count")
    private int argCount;

    @JsonProperty("guard")
    private List<String> guard = new ArrayList<>();

    @JsonProperty("enum_constant")
    @JsonInclude(JsonInclude.Include.NON_NULL)
    private EnumConstantIR enumConstant;

    public CallIR() {}

    public CallIR(String file, int line, int col, String callee, String receiver, String kind, int argCount, List<String> guard, EnumConstantIR enumConstant) {
        this.callSiteIdGuess = null;
        this.file = file;
        this.line = line;
        this.col = col;
        this.callee = callee;
        this.receiver = receiver;
        this.kind = kind;
        this.argCount = argCount;
        this.guard = guard != null ? guard : new ArrayList<>();
        this.enumConstant = enumConstant;
    }

    public String getCallSiteIdGuess() {
        return callSiteIdGuess;
    }

    public void setCallSiteIdGuess(String callSiteIdGuess) {
        this.callSiteIdGuess = callSiteIdGuess;
    }

    public String getFile() {
        return file;
    }

    public void setFile(String file) {
        this.file = file;
    }

    public int getLine() {
        return line;
    }

    public void setLine(int line) {
        this.line = line;
    }

    public int getCol() {
        return col;
    }

    public void setCol(int col) {
        this.col = col;
    }

    public String getCallee() {
        return callee;
    }

    public void setCallee(String callee) {
        this.callee = callee;
    }

    public String getReceiver() {
        return receiver;
    }

    public void setReceiver(String receiver) {
        this.receiver = receiver;
    }

    public String getKind() {
        return kind;
    }

    public void setKind(String kind) {
        this.kind = kind;
    }

    public int getArgCount() {
        return argCount;
    }

    public void setArgCount(int argCount) {
        this.argCount = argCount;
    }

    public List<String> getGuard() {
        return guard;
    }

    public void setGuard(List<String> guard) {
        this.guard = guard;
    }

    public EnumConstantIR getEnumConstant() {
        return enumConstant;
    }

    public void setEnumConstant(EnumConstantIR enumConstant) {
        this.enumConstant = enumConstant;
    }
}

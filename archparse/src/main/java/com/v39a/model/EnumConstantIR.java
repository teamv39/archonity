package com.v39a.model;

import com.fasterxml.jackson.annotation.JsonProperty;

public class EnumConstantIR {
    @JsonProperty("type")
    private String type;

    @JsonProperty("constant")
    private String constant;

    public EnumConstantIR() {}

    public EnumConstantIR(String type, String constant) {
        this.type = type;
        this.constant = constant;
    }

    public String getType() {
        return type;
    }

    public void setType(String type) {
        this.type = type;
    }

    public String getConstant() {
        return constant;
    }

    public void setConstant(String constant) {
        this.constant = constant;
    }
}

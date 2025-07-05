DROP TABLE IF EXISTS GenerationStepLogs;
DROP TABLE IF EXISTS GenerationLogs;
DROP TABLE IF EXISTS StepDefinitions;

CREATE TABLE GenerationLogs (
    request_id VARCHAR(50) PRIMARY KEY,
    prompt NVARCHAR(MAX),
    content_type VARCHAR(10),
    resolution VARCHAR(20),
    frame_rate FLOAT,
    duration_seconds FLOAT,
    status VARCHAR(20),            
    created_at DATETIME DEFAULT GETUTCDATE()
);

CREATE TABLE StepDefinitions (
    step_id INT PRIMARY KEY,
    step_name VARCHAR(100) UNIQUE,  
    description NVARCHAR(MAX)      
);

INSERT INTO StepDefinitions (step_id, step_name, description) VALUES
(1, 'Script Generation', 'Generate structured script from prompt'),
(2, 'Audio Synthesis', 'Convert script into voice audio clips'),
(3, 'Video Generation', 'Compile visuals, narration, and encode final video');


CREATE TABLE GenerationStepLogs (
    id INT IDENTITY PRIMARY KEY,
    request_id VARCHAR(50),
    step_id INT,
    status VARCHAR(20),
    error_message NVARCHAR(MAX) NULL,
    duration_seconds FLOAT,
    timestamp DATETIME DEFAULT GETUTCDATE(),

    CONSTRAINT FK_Request FOREIGN KEY (request_id)
        REFERENCES GenerationLogs(request_id)
        ON DELETE CASCADE,

    CONSTRAINT FK_StepDefinition FOREIGN KEY (step_id)
        REFERENCES StepDefinitions(step_id)
);

